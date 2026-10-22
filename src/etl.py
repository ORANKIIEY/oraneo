"""Backward-compatible CLI and reusable validation -> dedupe -> transform -> load."""
from __future__ import annotations
import argparse
import logging
import sqlite3
from pathlib import Path
import pandas as pd
try:
    from .validation import REQUIRED_COLUMNS, read_csv, validate
    from .warehouse import initialize, new_run, finish_failed, commit_run, connect
except ImportError:  # support `python src/etl.py` and original tests importing etl
    from validation import REQUIRED_COLUMNS, read_csv, validate
    from warehouse import initialize, new_run, finish_failed, commit_run, connect

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


def load(clean: pd.DataFrame, rejected: pd.DataFrame, db_path: str):
    """Compatibility entrypoint; load a verified snapshot with an audit run."""
    initialize(db_path)
    run_id = new_run(db_path,'legacy-loaded-frame')
    from types import SimpleNamespace
    try:
        result = SimpleNamespace(clean=clean,rejected=rejected,duplicates=pd.DataFrame(),issues=pd.DataFrame(),
                                 input_count=len(clean)+len(rejected), missing={})
        commit_run(db_path,run_id,result)
    except Exception as e:
        finish_failed(db_path,run_id,str(e))
        raise


def run(raw_path: str, db_path: str, processed_dir: str, run_id: str | None = None) -> dict:
    if run_id is None: run_id = new_run(db_path, Path(raw_path).name)
    try:
        df = extract(raw_path)
        result = validate(df)
        commit_run(db_path,run_id,result)
        out = Path(processed_dir)
        out.mkdir(parents=True, exist_ok=True)
        # Only write this derivative after transaction commit. Atomic filesystem replacement.
        tmp = out / 'sales_clean.tmp'
        result.clean.to_csv(tmp,index=False)
        tmp.replace(out/'sales_clean.csv')
        return {'run_id':run_id,'raw':result.input_count,'unique':result.input_count-len(result.duplicates),
                'duplicates':len(result.duplicates),'clean':len(result.clean),'rejected':len(result.rejected)}
    except Exception as e:
        log.exception('Pipeline failed')
        # Do not incorrectly mark an already committed DB success as a failure on CSV export.
        with connect(db_path) as conn:
            current=conn.execute('SELECT status FROM pipeline_runs WHERE id=?',(run_id,)).fetchone()
        if current and current['status']=='running': finish_failed(db_path,run_id,str(e))
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--raw',default=str(ROOT/'data/raw/sales_raw.csv'))
    p.add_argument('--db',default=str(ROOT/'data/warehouse.db'))
    p.add_argument('--processed',default=str(ROOT/'data/processed'))
    a=p.parse_args();logging.basicConfig(level=logging.INFO)
    print(run(a.raw,a.db,a.processed))
