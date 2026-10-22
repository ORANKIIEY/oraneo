"""New v2 automation, anomaly rules, and explainable insights tests."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from src.etl import run
from src.warehouse import connect, initialize
from backend.app import automation as a
from backend.app.intelligence import build


def db_ready(tmp_path):
    db=str(tmp_path/'test.db')
    initialize(db)
    a.setup(db)
    return db


def test_automation_defaults_disabled(tmp_path):
    db=db_ready(tmp_path)
    result=a.get_settings(db)
    assert result['enabled'] is False
    assert result['interval_minutes']==1440
    assert result['next_run_at'] is None
    assert a.list_alerts(db)['unread']==0


def test_schedule_persisted_and_paused(tmp_path):
    db=db_ready(tmp_path)
    enabled=a.change_settings(db,enabled=True,interval_minutes=60,rejection_threshold=1.5,duplicate_threshold=2)
    assert enabled['enabled'] and enabled['next_run_at']
    assert a.get_settings(db)['rejection_threshold']==1.5
    # Editing threshold alone must not push the deadline farther away.
    changed=a.change_settings(db,enabled=True,interval_minutes=60,rejection_threshold=3,duplicate_threshold=2)
    assert changed['next_run_at']==enabled['next_run_at']
    disabled=a.change_settings(db,enabled=False,interval_minutes=60,rejection_threshold=3,duplicate_threshold=2)
    assert disabled['next_run_at'] is None
    with pytest.raises(ValueError):a.change_settings(db,enabled=True,interval_minutes=1,rejection_threshold=0,duplicate_threshold=0)


def test_claim_due_atomic(tmp_path):
    db=db_ready(tmp_path)
    a.change_settings(db,enabled=True,interval_minutes=15,rejection_threshold=5,duplicate_threshold=5)
    assert not a.claim_due(db)
    past=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='seconds')
    with connect(db) as c:c.execute('UPDATE automation_settings SET next_run_at=? WHERE id=1',(past,))
    assert a.claim_due(db) is True
    assert a.claim_due(db) is False
    assert a.get_settings(db)['last_triggered_at']


def test_scheduled_pipeline_and_notifications(tmp_path,project_paths):
    raw,_,processed=project_paths
    db=db_ready(tmp_path)
    a.change_settings(db,enabled=True,interval_minutes=15,rejection_threshold=0,duplicate_threshold=0)
    past=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='seconds')
    with connect(db) as c:c.execute('UPDATE automation_settings SET next_run_at=? WHERE id=1',(past,))
    run_id=a.process_due(db,raw,processed)
    assert run_id
    assert a.process_due(db,raw,processed) is None
    with connect(db) as c:
        r=c.execute('SELECT * FROM pipeline_runs WHERE id=?',(run_id,)).fetchone()
        assert r['status']=='success'
        assert r['raw_count']==r['accepted_count']+r['rejected_count']+r['duplicate_count']
    before=a.list_alerts(db)['unread']
    a.evaluate_run(db,run_id)
    assert a.list_alerts(db)['unread']==before
    if before:
        first=a.list_alerts(db,open_only=True)['items'][0]
        assert a.acknowledge(db,first['id'])
        assert a.list_alerts(db)['unread']==before-1


def test_failed_run_creates_single_alert(tmp_path):
    db=db_ready(tmp_path)
    from src.warehouse import new_run,finish_failed
    rid=new_run(db,'bad.csv')
    finish_failed(db,rid,'Incorrect CSV schema')
    a.evaluate_run(db,rid)
    a.evaluate_run(db,rid)
    items=a.list_alerts(db)['items']
    assert len(items)==1
    assert 'Incorrect CSV schema' in items[0]['detail']
    assert items[0]['severity']=='critical'


def test_insights_without_data(tmp_path):
    db=db_ready(tmp_path)
    result=build(db)
    assert result['current_month'] is None
    assert result['revenue_change_pct'] is None
    assert any('No sales snapshot' in s['title'] for s in result['signals'])


def test_insights_exactly_match_sqlite(tmp_path,project_paths):
    raw,_,processed=project_paths
    db=db_ready(tmp_path)
    run(str(raw),db,str(processed))
    result=build(db)
    with connect(db) as c:
        expected=c.execute('SELECT ROUND(SUM(revenue),2) FROM fact_sales').fetchone()[0]
    assert result['total_revenue']==expected
    assert result['top_city']['revenue'] > 0
    assert result['freshness_hours'] is not None
    assert 'forecast' in result['methodology']


def test_automation_endpoints(api_client):
    response=api_client.get('/api/v1/automation')
    assert response.status_code==200
    assert response.json()['settings']['enabled'] is False
    change=api_client.put('/api/v1/automation',json={'enabled':True,'interval_minutes':60,'rejection_threshold':7,'duplicate_threshold':4})
    assert change.status_code==200
    assert change.json()['enabled'] is True
    assert api_client.put('/api/v1/automation',json={'enabled':True,'interval_minutes':7,'rejection_threshold':7,'duplicate_threshold':4}).status_code==422
    assert api_client.get('/api/v1/intelligence').status_code==200
    assert api_client.get('/api/v1/alerts').json()['unread']==0
    assert api_client.post('/api/v1/alerts/999/acknowledge').status_code==404


def test_manual_pipeline_run_evaluates_guardrails(api_client):
    api_client.put('/api/v1/automation',json={
        'enabled':False,'interval_minutes':1440,'rejection_threshold':0,'duplicate_threshold':0})
    created=api_client.post('/api/v1/runs',json={})
    assert created.status_code==202
    rid=created.json()['run_id']
    detail=api_client.get(f'/api/v1/runs/{rid}').json()
    assert detail['status']=='success'
    alerts=api_client.get('/api/v1/alerts').json()
    assert all(x['run_id']==rid for x in alerts['items'])
    assert alerts['unread']>=1


def test_schedule_skips_concurrent_run(tmp_path,project_paths):
    raw,_,processed=project_paths
    db=db_ready(tmp_path)
    a.change_settings(db,enabled=True,interval_minutes=15,rejection_threshold=5,duplicate_threshold=5)
    from src.warehouse import new_run
    existing=new_run(db,'manual.csv')
    past=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='seconds')
    with connect(db) as c:c.execute('UPDATE automation_settings SET next_run_at=? WHERE id=1',(past,))
    assert a.process_due(db,raw,processed) is None
    with connect(db) as c:
        assert c.execute('SELECT status FROM pipeline_runs WHERE id=?',(existing,)).fetchone()[0]=='running'
        assert c.execute('SELECT COUNT(*) FROM pipeline_runs').fetchone()[0]==1
    assert 'Scheduled run skipped' in [x['title'] for x in a.list_alerts(db)['items']]
