"""SQLite transactional warehouse and durable run metadata."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_sales (
 order_id TEXT PRIMARY KEY NOT NULL, order_date TEXT NOT NULL, customer_id TEXT NOT NULL,
 city TEXT NOT NULL, product TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price REAL NOT NULL CHECK(unit_price>0), revenue REAL NOT NULL CHECK(revenue>0),
 order_month TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_month ON fact_sales(order_month);
CREATE INDEX IF NOT EXISTS idx_fact_city ON fact_sales(city);
CREATE INDEX IF NOT EXISTS idx_fact_product ON fact_sales(product);
CREATE INDEX IF NOT EXISTS idx_fact_customer ON fact_sales(customer_id);
CREATE TABLE IF NOT EXISTS pipeline_runs (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, input_ref TEXT, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL CHECK(status IN ('running','success','failed','interrupted')),
 raw_count INTEGER NOT NULL DEFAULT 0, unique_count INTEGER NOT NULL DEFAULT 0,
 duplicate_count INTEGER NOT NULL DEFAULT 0, accepted_count INTEGER NOT NULL DEFAULT 0,
 rejected_count INTEGER NOT NULL DEFAULT 0, duration_seconds REAL,
 error TEXT, log TEXT NOT NULL DEFAULT '', missing_json TEXT NOT NULL DEFAULT '{}',
 export_status TEXT, processed_dir TEXT, export_error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_only_one_running ON pipeline_runs(status) WHERE status='running';
CREATE TABLE IF NOT EXISTS rejected_sales (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES pipeline_runs(id), source_row INTEGER NOT NULL,
 order_id TEXT, raw_json TEXT NOT NULL, reasons_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rejected_run ON rejected_sales(run_id);
CREATE TABLE IF NOT EXISTS duplicate_audit (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES pipeline_runs(id), source_row INTEGER NOT NULL,
 order_id TEXT, raw_json TEXT NOT NULL, reasons_json TEXT NOT NULL, disposition TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_duplicates_run ON duplicate_audit(run_id);
CREATE TABLE IF NOT EXISTS quality_issues (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES pipeline_runs(id), source_row INTEGER NOT NULL,
 reason TEXT NOT NULL, column_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issues_run ON quality_issues(run_id);
CREATE TABLE IF NOT EXISTS report_history (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, generated_at TEXT NOT NULL, path TEXT NOT NULL,
 start_date TEXT, end_date TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connect(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
    finally:
        conn.close()


def initialize(db_path: str, recover: bool = False):
    with connect(db_path) as conn:
        # Safely preserve the original schema/data when opening an old database.
        exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fact_sales'").fetchone()
        if exists and not any(r['pk'] for r in conn.execute('PRAGMA table_info(fact_sales)').fetchall()):
            conn.execute('ALTER TABLE fact_sales RENAME TO legacy_fact_sales')
            if conn.execute("SELECT name FROM sqlite_master WHERE name='rejected_sales'").fetchone():
                conn.execute('ALTER TABLE rejected_sales RENAME TO legacy_rejected_sales')
        conn.executescript(SCHEMA)
        if not any(col['name']=='input_ref' for col in conn.execute('PRAGMA table_info(pipeline_runs)')):
            conn.execute('ALTER TABLE pipeline_runs ADD COLUMN input_ref TEXT')
        if not any(col['name']=='export_status' for col in conn.execute('PRAGMA table_info(pipeline_runs)')):
            conn.execute("ALTER TABLE pipeline_runs ADD COLUMN export_status TEXT")
        if not any(col['name']=='processed_dir' for col in conn.execute('PRAGMA table_info(pipeline_runs)')):
            conn.execute("ALTER TABLE pipeline_runs ADD COLUMN processed_dir TEXT")
        if not any(col['name']=='export_error' for col in conn.execute('PRAGMA table_info(pipeline_runs)')):
            conn.execute("ALTER TABLE pipeline_runs ADD COLUMN export_error TEXT")
        if recover:
            conn.execute("UPDATE pipeline_runs SET status='interrupted',finished_at=?,error='Process interrupted before completion' WHERE status='running'", (now(),))
            try:
                try:
                    from .etl import retry_failed_exports
                except ImportError:
                    from etl import retry_failed_exports
                retry_failed_exports(db_path)
            except Exception:
                pass


def new_run(db_path: str, filename: str, input_ref: str | None = None) -> str:
    initialize(db_path)
    run_id = uuid.uuid4().hex[:16]
    with connect(db_path) as conn:
        conn.execute("INSERT INTO pipeline_runs(id, filename,input_ref,started_at,status,log) VALUES(?,?,?,?,'running',?)",
                     (run_id, filename, input_ref, now(), f"[{now()}] Started {filename}"))
    return run_id


def finish_failed(db_path: str, run_id: str, error: str):
    with connect(db_path) as conn:
        start = conn.execute('SELECT started_at,log FROM pipeline_runs WHERE id=?',(run_id,)).fetchone()
        if not start: return
        duration = (datetime.fromisoformat(now()) - datetime.fromisoformat(start['started_at'])).total_seconds()
        conn.execute("UPDATE pipeline_runs SET status='failed',finished_at=?,error=?,duration_seconds=?,log=? WHERE id=?",
                     (now(), error[:500], max(duration,0), start['log']+'\nERROR: '+error[:500],run_id))


def update_export_status(db_path: str, run_id: str, status: str, error: str | None = None, processed_dir: str | None = None) -> None:
    """Track whether an export is pending, complete, or failed for a given run."""
    with connect(db_path) as conn:
        row = conn.execute('SELECT log, processed_dir FROM pipeline_runs WHERE id=?', (run_id,)).fetchone()
        if not row: return
        target_dir = str(processed_dir) if processed_dir else row['processed_dir']
        log_entry = f"\n[{now()}] CSV export {status}"
        if error:
            log_entry += f": {error[:300]}"
        conn.execute(
            '''UPDATE pipeline_runs SET export_status=?, export_error=?, processed_dir=?, log=log||? WHERE id=?''',
            (status, error[:500] if error else None, target_dir, log_entry, run_id)
        )


def get_export_status(db_path: str, run_id: str | None = None) -> dict:
    """Inspect the export disposition of the warehouse or a specific pipeline run."""
    with connect(db_path) as conn:
        cols = {col['name'] for col in conn.execute('PRAGMA table_info(pipeline_runs)')}
        has_col = 'export_status' in cols
        if run_id:
            row = conn.execute('SELECT id, status, export_status, export_error, processed_dir FROM pipeline_runs WHERE id=?', (run_id,)).fetchone()
            if not row:
                return {'run_id': run_id, 'found': False}
            return {
                'run_id': row['id'],
                'run_status': row['status'],
                'export_status': row['export_status'] if has_col else 'unknown',
                'export_error': row['export_error'] if 'export_error' in cols else None,
                'processed_dir': row['processed_dir'] if 'processed_dir' in cols else None,
                'found': True
            }
        else:
            latest = conn.execute("SELECT id, status, export_status, export_error, processed_dir FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC, id DESC LIMIT 1").fetchone()
            pending = conn.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='success' AND export_status='pending'").fetchone()[0] if has_col else 0
            failed = conn.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='success' AND export_status='failed'").fetchone()[0] if has_col else 0
            return {
                'latest_run_id': latest['id'] if latest else None,
                'latest_export_status': latest['export_status'] if (latest and has_col) else None,
                'pending_exports': pending,
                'failed_exports': failed,
            }


def diagnostics(db_path: str, processed_dir: str | Path | None = None, retry_failed: bool = True) -> dict:
    """Readiness and export diagnostics for the warehouse.

    Reports database readiness, sales count, run statuses, and export health.
    If retry_failed is True and there are pending/failed exports, attempts to retry them.
    """
    retried = []
    if retry_failed:
        try:
            try:
                from .etl import retry_failed_exports
            except ImportError:
                from etl import retry_failed_exports
            retried = retry_failed_exports(db_path, default_processed_dir=processed_dir)
        except Exception:
            pass

    required = ['fact_sales', 'pipeline_runs', 'rejected_sales', 'duplicate_audit']
    with connect(db_path) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [table for table in required if table not in tables]
        orders = c.execute('SELECT COUNT(*) FROM fact_sales').fetchone()[0] if not missing else 0
        latest = c.execute('SELECT * FROM pipeline_runs ORDER BY started_at DESC, id DESC LIMIT 1').fetchone() if not missing else None

        cols = {col['name'] for col in c.execute('PRAGMA table_info(pipeline_runs)')} if 'pipeline_runs' in tables else set()
        has_export_status = 'export_status' in cols

        pending_count = 0
        failed_count = 0
        latest_export = None
        if has_export_status and not missing:
            pending_count = c.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='success' AND export_status='pending'").fetchone()[0]
            failed_count = c.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='success' AND export_status='failed'").fetchone()[0]
            latest_succ = c.execute("SELECT export_status FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC, id DESC LIMIT 1").fetchone()
            if latest_succ:
                latest_export = latest_succ['export_status']

    target_dir = Path(processed_dir) if processed_dir else (Path(db_path).parent / 'processed')
    csv_file = target_dir / 'sales_clean.csv'
    csv_exists = csv_file.is_file()

    if latest_export:
        overall_status = latest_export
    elif csv_exists and not failed_count and not pending_count:
        overall_status = 'complete'
    elif failed_count:
        overall_status = 'failed'
    elif pending_count:
        overall_status = 'pending'
    else:
        overall_status = 'none'

    return {
        'ready': not missing,
        'warehouse_exists': Path(db_path).is_file(),
        'sales_rows': orders,
        'latest_run_status': latest['status'] if latest else None,
        'latest_run_id': latest['id'] if latest else None,
        'latest_export_status': latest_export,
        'export_status': overall_status,
        'pending_exports': pending_count,
        'failed_exports': failed_count,
        'export_file_exists': csv_exists,
        'retried_exports': retried,
        'missing_tables': missing,
    }


def commit_run(db_path: str, run_id: str, result, processed_dir: str | None = None) -> None:
    """Single atomic transaction: facts, audit, and success flag. Replace latest snapshot."""
    with connect(db_path) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM fact_sales')
            clean = result.clean
            if not clean.empty:
                conn.executemany('''INSERT INTO fact_sales(order_id,order_date,customer_id,city,product,quantity,unit_price,revenue,order_month)
                    VALUES(:order_id,:order_date,:customer_id,:city,:product,:quantity,:unit_price,:revenue,:order_month)''',clean.to_dict('records'))
            for table, frame, cols in [
                ('rejected_sales',result.rejected,'source_row,order_id,raw_json,reasons_json'),
                ('duplicate_audit',result.duplicates,'source_row,order_id,raw_json,reasons_json,disposition'),
                ('quality_issues',result.issues,'source_row,reason,column_name')]:
                if not frame.empty:
                    keys = cols.split(',')
                    fields = ','.join(['run_id']+keys)
                    holders = ','.join('?' for _ in range(len(keys)+1))
                    conn.executemany(f'INSERT INTO {table}({fields}) VALUES({holders})',
                                     [(run_id, *[r[k] for k in keys]) for r in frame.to_dict('records')])
            row = conn.execute('SELECT started_at,log FROM pipeline_runs WHERE id=?', (run_id,)).fetchone()
            if not row: raise ValueError('Run metadata missing')
            duration = (datetime.fromisoformat(now())-datetime.fromisoformat(row['started_at'])).total_seconds()
            conn.execute('''UPDATE pipeline_runs SET status='success',finished_at=?,raw_count=?,unique_count=?,
                duplicate_count=?,accepted_count=?,rejected_count=?,duration_seconds=?,missing_json=?,
                export_status='pending',processed_dir=?,log=? WHERE id=?''',
                (now(),result.input_count,result.input_count-len(result.duplicates),len(result.duplicates),
                 len(result.clean),len(result.rejected),max(duration,0),json.dumps(result.missing),
                 str(processed_dir) if processed_dir else None,
                 row['log']+f'\n[{now()}] Committed {len(result.clean)} accepted, {len(result.rejected)} rejected, {len(result.duplicates)} duplicate rows. CSV export pending.',run_id))
            conn.execute('COMMIT')
        except BaseException:
            conn.execute('ROLLBACK')
            raise
