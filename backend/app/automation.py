"""Durable, local-only recurring ETL execution and in-app quality notifications.

A single Uvicorn process owns the scheduler. No cron or third-party service required.
Scheduled tasks run only while the API process is running. A missed interval runs
at most once after restart. All schedule state and alert dispositions live in SQLite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
import logging
import sqlite3

from src.etl import run
from src.warehouse import connect, new_run

logger = logging.getLogger(__name__)
INTERVALS = (15, 60, 360, 1440)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat(timespec='seconds')


def setup(db: str) -> None:
    with connect(db) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS automation_settings (
            id INTEGER PRIMARY KEY CHECK (id=1), enabled INTEGER NOT NULL DEFAULT 0,
            interval_minutes INTEGER NOT NULL DEFAULT 1440,
            rejection_threshold REAL NOT NULL DEFAULT 5.0,
            duplicate_threshold REAL NOT NULL DEFAULT 3.0,
            next_run_at TEXT, last_triggered_at TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS operations_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE, category TEXT NOT NULL, severity TEXT NOT NULL,
            title TEXT NOT NULL, detail TEXT NOT NULL,
            run_id TEXT, created_at TEXT NOT NULL, acknowledged_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_alert_open ON operations_alerts(acknowledged_at,created_at);
        ''')
        c.execute('''INSERT OR IGNORE INTO automation_settings
            (id,enabled,interval_minutes,rejection_threshold,duplicate_threshold,updated_at)
            VALUES (1,0,1440,5,3,?)''', (timestamp(),))


def get_settings(db: str) -> dict:
    setup(db)
    with connect(db) as c:
        d = dict(c.execute('SELECT * FROM automation_settings WHERE id=1').fetchone())
    d['enabled'] = bool(d['enabled'])
    d['schedule_scope'] = 'local_api_process'
    return d


def change_settings(db: str, *, enabled: bool, interval_minutes: int,
                    rejection_threshold: float, duplicate_threshold: float) -> dict:
    if interval_minutes not in INTERVALS:
        raise ValueError('Unsupported schedule interval')
    if not 0 <= rejection_threshold <= 100 or not 0 <= duplicate_threshold <= 100:
        raise ValueError('Alert thresholds must be between 0 and 100')
    setup(db)
    now = utcnow()
    with connect(db) as c:
        previous = c.execute('SELECT enabled,interval_minutes,next_run_at FROM automation_settings WHERE id=1').fetchone()
        # Adjust the trigger when enabling or changing cadence. Preserve it when
        # changing just the thresholds to avoid postponing a scheduled run.
        if enabled and (not previous['enabled'] or interval_minutes != previous['interval_minutes'] or not previous['next_run_at']):
            next_at = timestamp(now + timedelta(minutes=interval_minutes))
        elif enabled:
            next_at = previous['next_run_at']
        else:
            next_at = None
        c.execute('''UPDATE automation_settings SET enabled=?, interval_minutes=?,
            rejection_threshold=?,duplicate_threshold=?,next_run_at=?,updated_at=? WHERE id=1''',
            (int(enabled),interval_minutes,rejection_threshold,duplicate_threshold,next_at,timestamp(now)))
    return get_settings(db)


def add_alert(db: str, key: str, category: str, severity: str, title: str,
              detail: str, run_id: str | None = None) -> None:
    with connect(db) as c:
        c.execute('''INSERT OR IGNORE INTO operations_alerts
            (event_key,category,severity,title,detail,run_id,created_at)
            VALUES(?,?,?,?,?,?,?)''',(key,category,severity,title,detail,run_id,timestamp()))


def evaluate_run(db: str, run_id: str) -> None:
    """Create at most one alert per type per run, using persisted thresholds."""
    config = get_settings(db)
    with connect(db) as c:
        run = c.execute('SELECT status,raw_count,rejected_count,duplicate_count,error FROM pipeline_runs WHERE id=?', (run_id,)).fetchone()
    if not run:
        return
    if run['status'] in ('failed', 'interrupted'):
        add_alert(db, f'run:{run_id}:failed', 'pipeline', 'critical',
                  'Pipeline execution failed', f'Run {run_id}: {run["error"] or run["status"]}', run_id)
        return
    if run['status'] != 'success' or not run['raw_count']:
        return
    rejection = 100 * run['rejected_count'] / run['raw_count']
    duplicates = 100 * run['duplicate_count'] / run['raw_count']
    if rejection > config['rejection_threshold']:
        add_alert(db, f'run:{run_id}:rejections', 'data_quality', 'warning',
                  'Rejection threshold exceeded',
                  f'{rejection:.2f}% rejected; configured limit {config["rejection_threshold"]:.2f}% (run {run_id}).', run_id)
    if duplicates > config['duplicate_threshold']:
        add_alert(db, f'run:{run_id}:duplicates', 'data_quality', 'warning',
                  'Duplicate threshold exceeded',
                  f'{duplicates:.2f}% duplicates; configured limit {config["duplicate_threshold"]:.2f}% (run {run_id}).', run_id)


def list_alerts(db: str, *, open_only: bool = False, limit: int = 80) -> dict:
    setup(db)
    condition = 'WHERE acknowledged_at IS NULL' if open_only else ''
    with connect(db) as c:
        items = [dict(row) for row in c.execute(
            f'SELECT id,category,severity,title,detail,run_id,created_at,acknowledged_at FROM operations_alerts {condition} ORDER BY created_at DESC,id DESC LIMIT ?',
            (limit,)).fetchall()]
        pending = c.execute('SELECT COUNT(*) FROM operations_alerts WHERE acknowledged_at IS NULL').fetchone()[0]
    return {'items': items, 'unread': pending}


def acknowledge(db: str, alert_id: int) -> bool:
    with connect(db) as c:
        result = c.execute('UPDATE operations_alerts SET acknowledged_at=COALESCE(acknowledged_at,?) WHERE id=?', (timestamp(),alert_id))
        return bool(result.rowcount)


def claim_due(db: str) -> bool:
    """Atomically advance the next fire time; avoids two threads claiming one slot."""
    setup(db)
    with connect(db) as c:
        try:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM automation_settings WHERE id=1').fetchone()
            if not row['enabled'] or not row['next_run_at'] or row['next_run_at'] > timestamp():
                c.execute('COMMIT')
                return False
            next_at = timestamp(utcnow() + timedelta(minutes=row['interval_minutes']))
            c.execute('UPDATE automation_settings SET next_run_at=?,last_triggered_at=?,updated_at=? WHERE id=1',
                      (next_at,timestamp(),timestamp()))
            c.execute('COMMIT')
            return True
        except BaseException:
            c.execute('ROLLBACK')
            raise


def process_due(db: str, raw: Path, processed: Path) -> str | None:
    """Perform at most one due run. Never overwrite an ongoing manual run."""
    if not claim_due(db):
        return None
    if not raw.is_file():
        add_alert(db, 'scheduler:missing-input:'+timestamp(), 'scheduler','critical',
                  'Scheduled run could not start', 'The configured default raw CSV is missing.')
        return None
    try:
        run_id = new_run(db, raw.name)
    except sqlite3.IntegrityError:
        # The unique running-job constraint protects the warehouse.
        add_alert(db, 'scheduler:busy:'+timestamp(), 'scheduler','warning',
                  'Scheduled run skipped', 'Another pipeline run was already in progress.')
        return None
    try:
        run(str(raw), db, str(processed), run_id=run_id)
    except Exception:
        logger.exception('Scheduled run %s failed', run_id)
    finally:
        evaluate_run(db, run_id)
    return run_id


class LocalScheduler:
    def __init__(self, db: str, raw: Path, processed: Path, poll_seconds: int = 5):
        self.db, self.raw, self.processed = db, raw, processed
        self.poll_seconds = poll_seconds
        self.stop_signal = Event()
        self.thread = Thread(target=self._loop, name='oraneo-scheduler', daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_signal.set()
        self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stop_signal.wait(self.poll_seconds):
            try:
                process_due(self.db, self.raw, self.processed)
            except Exception:
                logger.exception('Local scheduler tick failed')
