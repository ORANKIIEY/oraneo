import sqlite3
import json
import pandas as pd
import pytest
from src.validation import validate
from src.etl import run
from src.warehouse import connect,commit_run,new_run,finish_failed,initialize
from src.generate_data import generate

def test_reconciliation_and_repeat_execution(project_paths):
    raw,db,processed=project_paths
    first=run(str(raw),str(db),str(processed))
    assert first['raw']==first['duplicates']+first['clean']+first['rejected']
    again=run(str(raw),str(db),str(processed))
    assert again['clean']==first['clean']
    with connect(str(db)) as c:
        assert c.execute('SELECT COUNT(*) FROM fact_sales').fetchone()[0]==first['clean']
        assert c.execute('SELECT COUNT(*) FROM pipeline_runs').fetchone()[0]==2
        assert c.execute('SELECT COUNT(*) FROM duplicate_audit').fetchone()[0]==first['duplicates']*2
        assert c.execute('SELECT COUNT(*) FROM rejected_sales').fetchone()[0]==first['rejected']*2
        assert all(r['status']=='success' for r in c.execute('SELECT status FROM pipeline_runs'))

def test_atomic_rollback_keeps_previous_warehouse(project_paths):
    raw,db,processed=project_paths
    good=run(str(raw),str(db),str(processed))
    invalid=validate(pd.DataFrame([{'order_id':'123','order_date':'2026-01-01',
       'customer_id':'C1','city':'Cape Town','product':'Laptop','quantity':'1','unit_price':'100'}]))
    invalid.clean=pd.concat([invalid.clean,invalid.clean],ignore_index=True)
    new_id=new_run(str(db),'problem.csv')
    with pytest.raises(sqlite3.IntegrityError):commit_run(str(db),new_id,invalid)
    finish_failed(str(db),new_id,'Duplicate primary key')
    with connect(str(db)) as c:
        assert c.execute('SELECT COUNT(*) FROM fact_sales').fetchone()[0]==good['clean']
        assert c.execute('SELECT status FROM pipeline_runs WHERE id=?',(new_id,)).fetchone()[0]=='failed'
        assert c.execute('SELECT COUNT(*) FROM rejected_sales WHERE run_id=?',(new_id,)).fetchone()[0]==0

def test_interrupted_run_recovered(tmp_path):
    db=str(tmp_path/'test.db');rid=new_run(db,'unfinished.csv')
    initialize(db,recover=True)
    with connect(db) as c:
        run_row=c.execute('SELECT status,error FROM pipeline_runs WHERE id=?',(rid,)).fetchone()
        assert run_row['status']=='interrupted'
        assert 'interrupted' in run_row['error']

def test_simultaneous_running_prevented(tmp_path):
    db=str(tmp_path/'test.db');new_run(db,'first.csv')
    with pytest.raises(sqlite3.IntegrityError):new_run(db,'second.csv')

def test_migrate_old_schema_preserves_data(tmp_path):
    db=str(tmp_path/'legacy.db')
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE fact_sales(order_id INTEGER,city TEXT)')
        c.execute("INSERT INTO fact_sales VALUES(1,'Durban')")
        c.execute('CREATE TABLE rejected_sales(order_id TEXT)')
    initialize(db)
    with connect(db) as c:
        assert c.execute('SELECT city FROM legacy_fact_sales').fetchone()[0]=='Durban'
        assert c.execute('SELECT COUNT(*) FROM fact_sales').fetchone()[0]==0
        assert c.execute("SELECT name FROM sqlite_master WHERE name='legacy_rejected_sales'").fetchone()
