"""Versioned local FastAPI application. All data originates in the SQLite warehouse."""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import csv
import base64
import binascii
import hmac
import os
import shutil
import io
import json
import logging
import re
import sqlite3
import uuid

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

from src.etl import extract, run
from src.validation import validate
from src.warehouse import initialize, new_run, connect
from src.pdf_report import produce
from . import config as cfg
from . import service as s
from . import automation as a
from . import intelligence as insight

logger=logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app:FastAPI):
    if bool(cfg.AUTH_USER) != bool(cfg.AUTH_PASSWORD):
        raise RuntimeError('Set both ORANEO_AUTH_USER and ORANEO_AUTH_PASSWORD, or neither')
    # A Render persistent disk is empty on first attach. Seed once from the
    # bundled demonstration warehouse; never overwrite an existing warehouse.
    database = Path(cfg.DATABASE)
    database.parent.mkdir(parents=True, exist_ok=True)
    if (os.getenv('ORANEO_SEED_ON_FIRST_BOOT', 'false').lower() == 'true'
        and not database.exists() and database.resolve() != cfg.SEED_DATABASE.resolve()):
        shutil.copy2(cfg.SEED_DATABASE, database)
        logger.info('Initialised persistent database from bundled sample')
    initialize(cfg.DATABASE,recover=True)
    a.setup(cfg.DATABASE)
    cfg.UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
    cfg.REPORT_DIR.mkdir(parents=True,exist_ok=True)
    scheduler = a.LocalScheduler(cfg.DATABASE, cfg.RAW_FILE, cfg.PROCESSED)
    if cfg.ENABLE_LOCAL_SCHEDULER:
        scheduler.start()
    try:
        yield
    finally:
        if cfg.ENABLE_LOCAL_SCHEDULER:
            scheduler.stop()

app=FastAPI(title='ORANEO Data Operations API',version='3.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=cfg.CORS_ORIGINS,allow_methods=['GET','POST','PUT'],allow_headers=['*'])

@app.middleware('http')
async def require_credentials(request: Request, call_next):
    # Render's HTTPS endpoint prompts the browser once with HTTP Basic auth;
    # no secret is embedded in frontend JavaScript or sent in URL parameters.
    if not cfg.AUTH_USER and not cfg.AUTH_PASSWORD:
        try:
            return await call_next(request)
        except sqlite3.Error:
            logger.exception('Warehouse database error during %s', request.url.path)
            return JSONResponse({'detail': 'Warehouse error. Inspect /api/v1/diagnostics and the FastAPI terminal.'}, status_code=503)
    if request.url.path == API + '/health':
        return await call_next(request)
    provided = request.headers.get('authorization', '')
    valid = False
    if provided.startswith('Basic '):
        try:
            decoded = base64.b64decode(provided[6:], validate=True).decode('utf-8')
            username, password = decoded.split(':', 1)
            valid = hmac.compare_digest(username, cfg.AUTH_USER) and hmac.compare_digest(password, cfg.AUTH_PASSWORD)
        except (ValueError, UnicodeError, binascii.Error):
            pass
    if not valid:
        return JSONResponse({'detail': 'Authentication required'}, status_code=401,
                            headers={'WWW-Authenticate': 'Basic realm="ORANEO"'})
    try:
        return await call_next(request)
    except sqlite3.Error:
        logger.exception('Warehouse database error during %s', request.url.path)
        return JSONResponse({'detail': 'Warehouse error. Inspect /api/v1/diagnostics and the FastAPI terminal.'}, status_code=503)

API='/api/v1'

class DateFilter(BaseModel):
    start_date:date|None=None
    end_date:date|None=None
    @model_validator(mode='after')
    def validate_dates(self):
        if self.start_date and self.end_date and self.start_date>self.end_date:
            raise ValueError('Start date cannot be after end date')
        return self

class ReportRequest(DateFilter):
    kind:str=Field(pattern='^(sales|quality|pipeline|filtered)$')

class RunRequest(BaseModel):
    upload_id: str|None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

class RunResponse(BaseModel):
    run_id:str
    status:str
    message:str

class Preview(BaseModel):
    upload_id:str
    filename:str
    raw_count:int
    unique_count:int
    accepted_count:int
    rejected_count:int
    duplicate_count:int
    missing_values:dict[str,int]

@app.get(API+'/health')
def health():
    try:
        with connect(cfg.DATABASE) as c:
            c.execute('SELECT 1').fetchone()
        return {'status':'ok','database':'connected','currency':cfg.CURRENCY}
    except sqlite3.Error:
        raise HTTPException(503,'Database unavailable')

@app.get(API+'/dashboard')
def dashboard():
    return {**s.dashboard(cfg.DATABASE),'currency':cfg.CURRENCY}

@app.get(API+'/analytics')
def analytics(start_date:date|None=None,end_date:date|None=None):
    validate_window(start_date,end_date)
    return {**s.analytics(cfg.DATABASE,as_date(start_date),as_date(end_date)),'currency':cfg.CURRENCY}

for name in ['monthly','cities','products','customers']:
    # Dedicated versioned endpoints, all share one underlying query service.
    def make_route(key):
        def route(start_date:date|None=None,end_date:date|None=None):
            validate_window(start_date,end_date)
            return s.analytics(cfg.DATABASE,as_date(start_date),as_date(end_date))[key]
        return route
    app.add_api_route(API+'/analytics/'+name,make_route(name),methods=['GET'],name='analytics_'+name)

def validate_window(start:date|None,end:date|None):
    if start and end and start>end: raise HTTPException(422,'Start date cannot be after end date')
def as_date(v):return v.isoformat() if v else None

@app.get(API+'/sales')
def sales(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),
          sort_by:str='order_date',sort_dir:str='desc',start_date:date|None=None,end_date:date|None=None,
          city:str|None=None,product:str|None=None,customer:str|None=None,search:str|None=Query(None,max_length=120)):
    validate_window(start_date,end_date)
    try:
        return s.sales(cfg.DATABASE,page,page_size,sort_by,sort_dir,start_date=as_date(start_date),end_date=as_date(end_date),
                       city=city,product=product,customer=customer,search=search)
    except ValueError as e:raise HTTPException(422,str(e))

@app.get(API+'/quality')
def quality(run_id:str|None=None):
    response=s.quality(cfg.DATABASE,run_id)
    if response is None:raise HTTPException(404,'Run not found')
    return response

@app.get(API+'/rejected')
def rejected(run_id:str|None=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),
             search:str=Query('',max_length=120),reason:str=Query('',max_length=120),include_duplicates:bool=False):
    return s.rejected(cfg.DATABASE,run_id,page,page_size,search,reason,include_duplicates)

def safe_csv(v):
    value=str(v) if v is not None else ''
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value

@app.get(API+'/rejected/export')
def export_rejected(run_id:str|None=None,include_duplicates:bool=False):
    # Streaming CSV avoids returning an unbounded JSON response.
    def data():
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(['source_row','order_id','disposition','reasons','original_json'])
        yield stream.getvalue();stream.seek(0);stream.truncate(0)
        page=1
        while True:
            chunk=s.rejected(cfg.DATABASE,run_id,page,500,'','',include_duplicates)
            for r in chunk['items']:
                writer.writerow([safe_csv(r['source_row']),safe_csv(r['order_id']),r['disposition'],
                                 safe_csv('; '.join(r['reasons'])),safe_csv(json.dumps(r['original'],ensure_ascii=False))])
                yield stream.getvalue();stream.seek(0);stream.truncate(0)
            if page*500>=chunk['total']:break
            page+=1
    return StreamingResponse(data(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="rejected_records.csv"'})

@app.get(API+'/runs')
def runs(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),
         status:str|None=Query(None,pattern='^(running|success|failed|interrupted)$'),
         filename:str|None=Query(None,max_length=120),start_date:date|None=None,end_date:date|None=None):
    validate_window(start_date,end_date)
    return s.run_history(cfg.DATABASE,page,page_size,status,filename,as_date(start_date),as_date(end_date))

@app.get(API+'/runs/{run_id}')
def run_detail(run_id:str):
    result=s.get_run(cfg.DATABASE,run_id)
    if not result:raise HTTPException(404,'Pipeline run not found')
    return result

@app.get(API+'/inputs/default/preview')
def default_input_preview():
    if not cfg.RAW_FILE.is_file():raise HTTPException(404,'Default raw CSV not found')
    try:
        result=validate(extract(str(cfg.RAW_FILE)))
    except ValueError as exc:raise HTTPException(422,str(exc)[:300])
    return {'filename':cfg.RAW_FILE.name,'raw_count':result.input_count,
            'unique_count':result.input_count-len(result.duplicates),
            'accepted_count':len(result.clean),'rejected_count':len(result.rejected),
            'duplicate_count':len(result.duplicates),'missing_values':result.missing}

@app.post(API+'/uploads/validate',response_model=Preview)
async def upload_csv(file:UploadFile=File(...)):
    name=Path(file.filename or '').name
    if not name.lower().endswith('.csv'):
        raise HTTPException(400,'Only .csv files are accepted')
    uid=uuid.uuid4().hex
    destination=cfg.UPLOAD_DIR/(uid+'.csv')
    cfg.UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
    total=0
    try:
        with destination.open('wb') as f:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total>cfg.MAX_UPLOAD_MB*1024*1024:raise HTTPException(413,'CSV exceeds upload size limit')
                f.write(chunk)
        if total==0:raise HTTPException(400,'Empty file')
        frame=extract(str(destination))
        result=validate(frame)
        (cfg.UPLOAD_DIR/(uid+'.json')).write_text(json.dumps({'filename':name}),encoding='utf8')
        return {'upload_id':uid,'filename':name,'raw_count':result.input_count,
                'unique_count':result.input_count-len(result.duplicates),
                'accepted_count':len(result.clean),'rejected_count':len(result.rejected),
                'duplicate_count':len(result.duplicates),'missing_values':result.missing}
    except HTTPException:
        destination.unlink(missing_ok=True);raise
    except (ValueError,OSError) as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(400,str(exc)[:300])
    finally:
        await file.close()

def execute_background(input_path:Path,run_id:str):
    try:
        run(str(input_path),cfg.DATABASE,str(cfg.PROCESSED),run_id=run_id)
    except Exception:
        logger.exception('Background pipeline failed for %s',run_id)
    finally:
        try:
            a.evaluate_run(cfg.DATABASE,run_id)
        except Exception:
            logger.exception('Could not evaluate quality alerts for run %s',run_id)

@app.post(API+'/runs',status_code=202,response_model=RunResponse)
def start_run(request:RunRequest,background_tasks:BackgroundTasks):
    if request.upload_id:
        input_path=cfg.UPLOAD_DIR/(request.upload_id+'.csv')
        info=cfg.UPLOAD_DIR/(request.upload_id+'.json')
        if not input_path.is_file() or not info.is_file():raise HTTPException(404,'Uploaded CSV not found; validate it again')
        filename=json.loads(info.read_text(encoding='utf8'))['filename']
    else:
        input_path=cfg.RAW_FILE
        filename=input_path.name
        if not input_path.is_file():raise HTTPException(404,'Default raw CSV not found')
    # Validate BEFORE setting status=running (and do not replace warehouse for invalid CSV).
    try:extract(str(input_path))
    except ValueError as e:raise HTTPException(422,str(e)[:300])
    try:run_id=new_run(cfg.DATABASE,filename,request.upload_id)
    except sqlite3.IntegrityError:raise HTTPException(409,'Another pipeline run is already in progress')
    background_tasks.add_task(execute_background,input_path,run_id)
    return {'run_id':run_id,'status':'running','message':'Pipeline execution started'}

@app.post(API+'/runs/{run_id}/retry',status_code=202,response_model=RunResponse)
def retry_run(run_id:str,background_tasks:BackgroundTasks):
    with connect(cfg.DATABASE) as c:
        item=c.execute('SELECT status,filename,input_ref FROM pipeline_runs WHERE id=?',(run_id,)).fetchone()
    if not item:raise HTTPException(404,'Run not found')
    if item['status'] not in ('failed','interrupted'):
        raise HTTPException(409,'Only failed or interrupted runs can be retried')
    input_ref=item['input_ref']
    source=cfg.UPLOAD_DIR/(input_ref+'.csv') if input_ref else cfg.RAW_FILE
    if not source.is_file():raise HTTPException(404,'Original input CSV no longer exists')
    try:extract(str(source))
    except ValueError as e:raise HTTPException(422,str(e)[:300])
    try:next_id=new_run(cfg.DATABASE,item['filename'],input_ref)
    except sqlite3.IntegrityError:raise HTTPException(409,'Another pipeline run is already running')
    background_tasks.add_task(execute_background,source,next_id)
    return {'run_id':next_id,'status':'running','message':'Retry started as a new run'}

@app.get(API+'/reports/preview')
def report_preview(kind:str=Query('sales',pattern='^(sales|quality|pipeline|filtered)$'),
                   start_date:date|None=None,end_date:date|None=None):
    validate_window(start_date,end_date)
    return {'kind':kind,'period':{'start_date':as_date(start_date),'end_date':as_date(end_date)},
            'currency':cfg.CURRENCY,'kpis':s.analytics(cfg.DATABASE,as_date(start_date),as_date(end_date))['kpis'],
            'quality':s.quality(cfg.DATABASE),'recent_runs':s.run_history(cfg.DATABASE,page_size=5)['items']}

@app.post(API+'/reports',status_code=201)
def create_report(request:ReportRequest):
    try:
        payload=produce(cfg.DATABASE,request.kind,as_date(request.start_date),as_date(request.end_date),cfg.CURRENCY)
        rid=uuid.uuid4().hex
        cfg.REPORT_DIR.mkdir(parents=True,exist_ok=True)
        target=cfg.REPORT_DIR/(rid+'.pdf')
        target.write_bytes(payload)
        with connect(cfg.DATABASE) as c:
            c.execute('INSERT INTO report_history (id,kind,generated_at,path,start_date,end_date) VALUES(?,?,datetime(\'now\'),?,?,?)',
                      (rid,request.kind,str(target),as_date(request.start_date),as_date(request.end_date)))
        return {'id':rid,'filename':f'oraneo_{request.kind}_{rid[:8]}.pdf','download_url':f'{API}/reports/{rid}/download'}
    except Exception:
        logger.exception('Report generation failed')
        raise HTTPException(500,'Unable to generate PDF report')

@app.get(API+'/reports/{report_id}/download')
def download_report(report_id:str):
    if not re.fullmatch('[a-f0-9]{32}',report_id):raise HTTPException(404,'Report not found')
    with connect(cfg.DATABASE) as c:
        report=c.execute('SELECT * FROM report_history WHERE id=?',(report_id,)).fetchone()
    if not report:raise HTTPException(404,'Report not found')
    target=(cfg.REPORT_DIR/(report_id+'.pdf')).resolve()
    if not target.is_relative_to(cfg.REPORT_DIR.resolve()) or not target.is_file():raise HTTPException(404,'Report file not found')
    return FileResponse(target,media_type='application/pdf',filename=f'oraneo_{report["kind"]}_{report_id[:8]}.pdf')


class AutomationRequest(BaseModel):
    enabled: bool
    interval_minutes: int = Field(ge=15, le=1440)
    rejection_threshold: float = Field(ge=0,le=100)
    duplicate_threshold: float = Field(ge=0,le=100)

@app.get(API+'/automation')
def get_automation():
    return {'settings':a.get_settings(cfg.DATABASE),'alerts':a.list_alerts(cfg.DATABASE,open_only=True,limit=8),'worker_active':cfg.ENABLE_LOCAL_SCHEDULER}

@app.put(API+'/automation')
def set_automation(payload:AutomationRequest):
    try:
        return a.change_settings(cfg.DATABASE,**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422,str(exc))

@app.get(API+'/alerts')
def get_alerts(open_only:bool=False,limit:int=Query(50,ge=1,le=100)):
    return a.list_alerts(cfg.DATABASE,open_only=open_only,limit=limit)

@app.post(API+'/alerts/{alert_id}/acknowledge')
def acknowledge_alert(alert_id:int):
    if not a.acknowledge(cfg.DATABASE,alert_id):
        raise HTTPException(404,'Alert not found')
    return {'id':alert_id,'acknowledged':True}

@app.get(API+'/intelligence')
def get_intelligence():
    return {**insight.build(cfg.DATABASE),'currency':cfg.CURRENCY}


@app.get(API + '/diagnostics')
def diagnostics():
    """Safe readiness information without leaking the filesystem path."""
    required = ['fact_sales','pipeline_runs','rejected_sales','duplicate_audit']
    try:
        with connect(cfg.DATABASE) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [table for table in required if table not in tables]
            orders = c.execute('SELECT COUNT(*) FROM fact_sales').fetchone()[0] if not missing else 0
            latest = c.execute('SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1').fetchone() if not missing else None
        return {'ready': not missing, 'warehouse_exists': Path(cfg.DATABASE).is_file(),
                'sales_rows': orders, 'latest_run_status': latest[0] if latest else None,
                'missing_tables': missing, 'frontend_built': (cfg.FRONTEND_DIST / 'index.html').is_file()}
    except sqlite3.Error:
        logger.exception('Database diagnostics failed')
        raise HTTPException(503, 'Database integrity check failed; inspect the backend logs')

@app.get('/{full_path:path}', include_in_schema=False)
def frontend_file(full_path: str):
    """A single Render service serves compiled React and the FastAPI routes."""
    if full_path.startswith(('api/', 'docs/', 'redoc/', 'openapi.json')):
        raise HTTPException(404, 'Not found')
    root = cfg.FRONTEND_DIST.resolve()
    if not (root / 'index.html').is_file():
        raise HTTPException(503, 'Frontend build missing. Run npm run build in frontend first.')
    candidate = (root / full_path).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(candidate)
    if '.' in Path(full_path).name:
        raise HTTPException(404, 'Asset not found')
    return FileResponse(root / 'index.html', media_type='text/html')
