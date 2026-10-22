"""Centralised, absolute and deployment-aware application paths."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]

def location(env: str, default: Path) -> Path:
    value = os.getenv(env)
    candidate = Path(value).expanduser() if value else default
    # Resolve relative environment paths from the project, not PowerShell's cwd.
    return (candidate if candidate.is_absolute() else ROOT / candidate).resolve()

DATABASE = str(location('SALES_DB_PATH', ROOT / 'data/warehouse.db'))
RAW_FILE = location('SALES_RAW_PATH', ROOT / 'data/raw/sales_raw.csv')
PROCESSED = location('SALES_PROCESSED_DIR', ROOT / 'data/processed')
UPLOAD_DIR = location('SALES_UPLOAD_DIR', ROOT / 'data/uploads')
REPORT_DIR = location('SALES_REPORT_DIR', ROOT / 'data/reports')
FRONTEND_DIST = location('ORANEO_FRONTEND_DIST', ROOT / 'frontend/dist')
SEED_DATABASE = ROOT / 'data/seed/warehouse_seed.db'
CURRENCY = os.getenv('SALES_CURRENCY', 'ZAR')
MAX_UPLOAD_MB = int(os.getenv('SALES_MAX_UPLOAD_MB', '10'))
CORS_ORIGINS = [s.strip() for s in os.getenv('SALES_CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if s.strip()]
ENABLE_LOCAL_SCHEDULER = os.getenv('ORANEO_SCHEDULER_ENABLED', 'true').lower() in ('true','1','yes')
AUTH_USER = os.getenv('ORANEO_AUTH_USER', '').strip()
AUTH_PASSWORD = os.getenv('ORANEO_AUTH_PASSWORD', '')
