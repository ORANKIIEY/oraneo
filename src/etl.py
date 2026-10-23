"""Backward-compatible CLI and reusable validation -> dedupe -> transform -> load."""
from __future__ import annotations
import argparse
import logging
import sqlite3
from pathlib import Path
import pandas as pd
try:
    from .validation import REQUIRED_COLUMNS, read_csv, validate
    from .warehouse import (initialize, new_run, finish_failed, commit_run, connect,
                            update_export_status, get_export_status, diagnostics)
except ImportError:  # support `python src/etl.py` and original tests importing etl
    from validation import REQUIRED_COLUMNS, read_csv, validate
    from warehouse import (initialize, new_run, finish_failed, commit_run, connect,
                           update_export_status, get_export_status, diagnostics)

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)


def extract(path: str) -> pd.DataFrame:
    if not Path(path).is_file(): raise ValueError('Input CSV file does not exist')
    df = read_csv(path)
    log.info('Extracted %s rows', len(df))
    return df


def transform(df: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    r = validate(df)
    return r.clean,r.rejected


def export_clean_csv(db_path: str, processed_dir: str | Path, run_id: str | None = None) -> Path:
    """Regenerate sales_clean.csv from the database (the source of truth)."""
    out = Path(processed_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / 'sales_clean.tmp'
    final = out / 'sales_clean.csv'

    with connect(db_path) as conn:
        df = pd.read_sql_query(
            'SELECT order_id, order_date, customer_id, city, product, quantity, unit_price, revenue, order_month FROM fact_sales ORDER BY rowid',
            conn
        )
    df.to_csv(tmp, index=False)
    tmp.replace(final)

    if run_id is None:
        with connect(db_path) as conn:
            latest = conn.execute("SELECT id FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC, id DESC LIMIT 1").fetchone()
            if latest:
                run_id = latest['id']
    if run_id:
        update_export_status(db_path, run_id, 'complete', processed_dir=str(processed_dir))
    return final


def retry_failed_exports(db_path: str, default_processed_dir: str | Path | None = None) -> list[dict]:
    """Retry any pending or failed CSV exports using the database as the source of truth."""
    results = []
    with connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'pipeline_runs' not in tables or 'fact_sales' not in tables:
            return results
        cols = {col['name'] for col in conn.execute('PRAGMA table_info(pipeline_runs)')}
        if 'export_status' not in cols:
            return results

        rows = conn.execute(
            "SELECT id, export_status, processed_dir FROM pipeline_runs WHERE status='success' AND export_status IN ('pending', 'failed') ORDER BY finished_at ASC, id ASC"
        ).fetchall()

    if not rows:
        return results

    for row in rows:
        rid = row['id']
        target_dir = row['processed_dir'] or default_processed_dir
        if not target_dir:
            target_dir = str(ROOT / 'data/processed')
        try:
            export_clean_csv(db_path, target_dir, run_id=rid)
            log.info('Recovered CSV export for run %s', rid)
            results.append({'run_id': rid, 'status': 'complete', 'processed_dir': str(target_dir), 'error': None})
        except Exception as e:
            log.exception('Retry export failed for run %s', rid)
            update_export_status(db_path, rid, 'failed', error=str(e), processed_dir=str(target_dir))
            results.append({'run_id': rid, 'status': 'failed', 'processed_dir': str(target_dir), 'error': str(e)})

    return results


def load(clean: pd.DataFrame, rejected: pd.DataFrame, db_path: str, processed_dir: str | None = None):
    """Compatibility entrypoint; load a verified snapshot with an audit run."""
    initialize(db_path)
    run_id = new_run(db_path,'legacy-loaded-frame')
    from types import SimpleNamespace
    try:
        result = SimpleNamespace(clean=clean,rejected=rejected,duplicates=pd.DataFrame(),issues=pd.DataFrame(),
                                 input_count=len(clean)+len(rejected), missing={})
        commit_run(db_path,run_id,result,processed_dir=processed_dir)
        if processed_dir:
            export_clean_csv(db_path, processed_dir, run_id=run_id)
    except Exception as e:
        finish_failed(db_path,run_id,str(e))
        raise


def run(raw_path: str, db_path: str, processed_dir: str, run_id: str | None = None) -> dict:
    if run_id is None: run_id = new_run(db_path, Path(raw_path).name)
    try:
        df = extract(raw_path)
        result = validate(df)
        commit_run(db_path, run_id, result, processed_dir=processed_dir)
    except Exception as e:
        log.exception('Pipeline failed')
        with connect(db_path) as conn:
            current = conn.execute('SELECT status FROM pipeline_runs WHERE id=?', (run_id,)).fetchone()
        if current and current['status'] == 'running':
            finish_failed(db_path, run_id, str(e))
        raise

    # Transaction committed to DB; now regenerate sales_clean.csv from database (source of truth).
    try:
        export_clean_csv(db_path, processed_dir, run_id=run_id)
    except Exception as e:
        log.exception('CSV export failed after successful DB commit for run %s', run_id)
        update_export_status(db_path, run_id, 'failed', error=str(e), processed_dir=processed_dir)
        raise

    return {
        'run_id': run_id,
        'raw': result.input_count,
        'unique': result.input_count - len(result.duplicates),
        'duplicates': len(result.duplicates),
        'clean': len(result.clean),
        'rejected': len(result.rejected),
        'export_status': 'complete',
    }


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--raw',default=str(ROOT/'data/raw/sales_raw.csv'))
    p.add_argument('--db',default=str(ROOT/'data/warehouse.db'))
    p.add_argument('--processed',default=str(ROOT/'data/processed'))
    p.add_argument('--retry-exports', action='store_true', help='Retry pending or failed CSV exports')
    p.add_argument('--diagnostics', action='store_true', help='Show warehouse and export diagnostics')
    a=p.parse_args();logging.basicConfig(level=logging.INFO)
    if a.retry_exports:
        print(retry_failed_exports(a.db, a.processed))
    elif a.diagnostics:
        print(diagnostics(a.db, a.processed))
    else:
        print(run(a.raw,a.db,a.processed))
