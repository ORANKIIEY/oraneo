import csv
import io
from pypdf import PdfReader
from src.validation import REQUIRED_COLUMNS

def test_api_endpoints_operate_on_actual_data(api_client):
    response=api_client.get('/api/v1/dashboard')
    assert response.status_code==200
    assert response.json()['kpis']['total_orders']==0
    job=api_client.post('/api/v1/runs',json={})
    assert job.status_code==202
    rid=job.json()['run_id']
    status=api_client.get('/api/v1/runs/'+rid).json()
    assert status['status']=='success'
    dash=api_client.get('/api/v1/dashboard').json()
    assert dash['kpis']['raw_count']==80+round(80*.02)
    assert dash['kpis']['accepted_count']+dash['kpis']['rejected_count']+dash['kpis']['duplicate_count']==dash['kpis']['raw_count']
    assert dash['analytics']['cities']
    assert all(x['name'] in ['Cape Town','Johannesburg','Durban','Pretoria','Gqeberha','Bloemfontein','Polokwane','Mbombela'] for x in dash['analytics']['cities'])
    assert api_client.get('/api/v1/health').json()['currency']=='ZAR'
    for route in ['/api/v1/analytics/monthly','/api/v1/analytics/cities','/api/v1/analytics/products','/api/v1/analytics/customers']:
        assert api_client.get(route).status_code==200
    assert api_client.get('/api/v1/quality').json()['run_id']==rid
    assert api_client.get('/api/v1/runs').json()['total']==1

def test_query_validation_and_paging(api_client):
    api_client.post('/api/v1/runs',json={})
    all_data=api_client.get('/api/v1/sales?page_size=5').json()
    assert len(all_data['items'])==5
    next_page=api_client.get('/api/v1/sales?page=2&page_size=5').json()
    assert all_data['items'][0]['order_id']!=next_page['items'][0]['order_id']
    city=all_data['items'][0]['city']
    city_data=api_client.get('/api/v1/sales',params={'city':city}).json()
    assert city_data['total']>0 and all(r['city']==city for r in city_data['items'])
    assert api_client.get('/api/v1/sales',params={'page':0}).status_code==422
    assert api_client.get('/api/v1/sales',params={'page_size':10000}).status_code==422
    assert api_client.get('/api/v1/sales',params={'sort_by':'revenue; DROP TABLE fact_sales'}).status_code==422
    assert api_client.get('/api/v1/sales',params={'start_date':'2026-10-10','end_date':'2026-01-01'}).status_code==422
    assert api_client.get('/api/v1/sales',params={'search':"' OR 1=1 --"}).json()['total']==0
    assert api_client.get('/api/v1/sales',params={'start_date':'2026-12-01'}).json()['total']==0

def test_invalid_upload_and_validated_csv(api_client):
    assert api_client.post('/api/v1/uploads/validate',files={'file':('hack.exe',b'not csv')}).status_code==400
    assert api_client.post('/api/v1/uploads/validate',files={'file':('empty.csv',b'')}).status_code==400
    assert api_client.post('/api/v1/uploads/validate',files={'file':('bad.csv',b'one,two\n3,4')}).status_code==400
    output=io.StringIO();writer=csv.DictWriter(output,fieldnames=REQUIRED_COLUMNS);writer.writeheader()
    writer.writerow({'order_id':'X1','order_date':'2026-10-01','customer_id':'C1','city':'Durban','product':'Keyboard','quantity':2,'unit_price':100})
    writer.writerow({'order_id':'X1','order_date':'2026-10-01','customer_id':'C1','city':'Durban','product':'Keyboard','quantity':2,'unit_price':100})
    result=api_client.post('/api/v1/uploads/validate',files={'file':('new-sales.csv',output.getvalue().encode())})
    assert result.status_code==200,result.text
    preview=result.json()
    assert preview['raw_count']==2 and preview['duplicate_count']==1
    job=api_client.post('/api/v1/runs',json={'upload_id':preview['upload_id']})
    assert job.status_code==202
    assert api_client.get('/api/v1/sales').json()['total']==1
    assert api_client.get('/api/v1/quality').json()['duplicate_count']==1
    assert api_client.post('/api/v1/runs',json={'upload_id':'a'*32}).status_code==404

def test_rejected_csv_export(api_client):
    api_client.post('/api/v1/runs',json={})
    r=api_client.get('/api/v1/rejected/export?include_duplicates=true')
    assert r.status_code==200
    assert r.headers['content-type'].startswith('text/csv')
    content=list(csv.DictReader(io.StringIO(r.text)))
    count=api_client.get('/api/v1/quality').json()
    assert len(content)==count['rejected_count']+count['duplicate_count']
    assert 'reasons' in content[0]

def test_pdf_report_is_real_native_text_and_filtered(api_client):
    api_client.post('/api/v1/runs',json={})
    kpis=api_client.get('/api/v1/analytics').json()['kpis']
    for kind in ['sales','quality','pipeline','filtered']:
        request={'kind':kind}
        if kind=='filtered':request.update(start_date='2026-01-01',end_date='2026-02-01')
        creation=api_client.post('/api/v1/reports',json=request)
        assert creation.status_code==201,creation.text
        pdf=api_client.get(creation.json()['download_url'])
        assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
        assert pdf.content.startswith(b'%PDF-')
        reader=PdfReader(io.BytesIO(pdf.content))
        text='\n'.join(p.extract_text() for p in reader.pages)
        assert len(reader.pages)>=1
        assert 'Executive summary' in text
        assert 'Methodology and limitations' in text
        if kind=='sales':
            assert len(reader.pages)>=2
            assert 'Monthly revenue trend' in text and 'Revenue by city' in text
            assert f"{kpis['total_revenue']:,.2f}" in text
        if kind=='quality': assert 'Rejection reasons' in text
        if kind=='pipeline': assert 'Pipeline execution summary' in text
        if kind=='filtered':assert '2026-01-01' in text and '2026-02-01' in text
    assert api_client.get('/api/v1/reports/../download').status_code in (404,405)
    assert api_client.get('/api/v1/reports/'+'f'*32+'/download').status_code==404
    assert api_client.post('/api/v1/reports',json={'kind':'nonsense'}).status_code==422

def test_pdf_empty_warehouse(api_client):
    creation=api_client.post('/api/v1/reports',json={'kind':'sales'})
    assert creation.status_code==201
    pdf=api_client.get(creation.json()['download_url'])
    assert 'No records match' in '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)

def test_large_pdf_repeats_table_headers_and_paginates(api_client):
    from backend.app import config as cfg
    from src.warehouse import connect,now
    api_client.post('/api/v1/runs',json={})
    with connect(cfg.DATABASE) as c:
        for i in range(65):
            c.execute("INSERT INTO pipeline_runs(id, filename, started_at, finished_at,status,raw_count,accepted_count) VALUES(?,?,?,?,?,?,?)",
                      (f'fakehistory{i:07d}',f'sample_{i}.csv',now(),now(),'failed',100,0))
    r=api_client.post('/api/v1/reports',json={'kind':'pipeline'})
    assert r.status_code==201,r.text
    pdf=api_client.get(r.json()['download_url'])
    reader=PdfReader(io.BytesIO(pdf.content))
    assert len(reader.pages)>=3
    pages=[p.extract_text() for p in reader.pages]
    assert 'Pipeline execution summary' in ''.join(pages)
    assert any('Run ID' in p for p in pages[2:])

def test_explicit_failed_run_retry(api_client):
    from backend.app import config as cfg
    from src.warehouse import new_run,finish_failed
    failed=new_run(cfg.DATABASE,'sales.csv')
    finish_failed(cfg.DATABASE,failed,'Simulated interrupted source')
    retry=api_client.post('/api/v1/runs/'+failed+'/retry')
    assert retry.status_code==202,retry.text
    assert retry.json()['run_id']!=failed
    assert api_client.get('/api/v1/runs/'+retry.json()['run_id']).json()['status']=='success'
    assert api_client.post('/api/v1/runs/'+retry.json()['run_id']+'/retry').status_code==409
