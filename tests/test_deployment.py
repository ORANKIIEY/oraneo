"""Tests for the deployment and startup regressions, on isolated databases."""
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import config as cfg
from backend.app.main import app
from src.warehouse import connect


def test_diagnostics_reports_real_initialized_warehouse(api_client):
    result = api_client.get('/api/v1/diagnostics')
    assert result.status_code == 200
    body = result.json()
    assert body['ready'] is True
    assert body['warehouse_exists'] is True
    assert body['sales_rows'] == 0
    assert body['missing_tables'] == []


def test_relative_config_paths_use_project_root(monkeypatch):
    monkeypatch.setenv('SALES_DB_PATH', 'data/example.db')
    assert cfg.location('SALES_DB_PATH', cfg.ROOT / 'unused') == (cfg.ROOT / 'data/example.db').resolve()


def test_spa_assets_and_browser_navigation(api_client, tmp_path, monkeypatch):
    frontend = tmp_path/'dist'
    assets = frontend/'assets'
    assets.mkdir(parents=True)
    (frontend/'index.html').write_text('<html>ORANEO SPA</html>', encoding='utf8')
    (assets/'hello.js').write_text('console.log("pink")', encoding='utf8')
    monkeypatch.setattr(cfg, 'FRONTEND_DIST', frontend)
    assert 'ORANEO SPA' in api_client.get('/').text
    assert 'ORANEO SPA' in api_client.get('/quality').text
    assert 'console.log' in api_client.get('/assets/hello.js').text
    assert api_client.get('/assets/missing.js').status_code == 404
    assert api_client.get('/api/v1/unknown').status_code == 404


def test_missing_built_frontend_returns_actionable_error(api_client, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'FRONTEND_DIST', tmp_path/'not-built')
    r = api_client.get('/pipeline')
    assert r.status_code == 503
    assert 'npm run build' in r.json()['detail']


def test_credential_protection_and_health_bypass(api_client, monkeypatch):
    monkeypatch.setattr(cfg, 'AUTH_USER', 'admin')
    monkeypatch.setattr(cfg, 'AUTH_PASSWORD', 'long-test-password')
    assert api_client.get('/api/v1/health').status_code == 200
    r = api_client.get('/api/v1/dashboard')
    assert r.status_code == 401
    assert r.headers['www-authenticate'].startswith('Basic')
    assert api_client.get('/api/v1/dashboard', auth=('admin','incorrect')).status_code == 401
    assert api_client.get('/api/v1/dashboard', auth=('admin','long-test-password')).status_code == 200


def test_persistent_database_is_seeded_once(tmp_path, monkeypatch):
    db = tmp_path/'mounted-disk'/'warehouse.db'
    monkeypatch.setattr(cfg, 'DATABASE', str(db))
    monkeypatch.setattr(cfg, 'UPLOAD_DIR', tmp_path/'uploads')
    monkeypatch.setattr(cfg, 'REPORT_DIR', tmp_path/'reports')
    monkeypatch.setenv('ORANEO_SEED_ON_FIRST_BOOT', 'true')
    with TestClient(app) as client:
        first = client.get('/api/v1/dashboard')
        assert first.status_code == 200
        assert first.json()['kpis']['total_orders'] > 0
        with connect(str(db)) as c:
            c.execute("UPDATE fact_sales SET city='NewCity' WHERE order_id=(SELECT order_id FROM fact_sales LIMIT 1)")
    with TestClient(app) as client:
        assert client.get('/api/v1/dashboard').status_code == 200
        with connect(str(db)) as c:
            assert c.execute("SELECT COUNT(*) FROM fact_sales WHERE city='NewCity'").fetchone()[0] == 1
