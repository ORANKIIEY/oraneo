import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

@pytest.fixture
def project_paths(tmp_path):
    from src.generate_data import generate
    raw=tmp_path/'raw.csv'
    generate(80,seed=31).to_csv(raw,index=False)
    return raw,tmp_path/'warehouse.db',tmp_path/'processed'

@pytest.fixture
def api_client(tmp_path,monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config,'DATABASE',str(tmp_path/'api.db'))
    monkeypatch.setattr(config,'RAW_FILE',tmp_path/'sales.csv')
    monkeypatch.setattr(config,'UPLOAD_DIR',tmp_path/'uploads')
    monkeypatch.setattr(config,'REPORT_DIR',tmp_path/'reports')
    monkeypatch.setattr(config,'PROCESSED',tmp_path/'processed')
    from src.generate_data import generate
    generate(80,seed=23).to_csv(config.RAW_FILE,index=False)
    from fastapi.testclient import TestClient
    from backend.app.main import app
    with TestClient(app) as client:yield client
