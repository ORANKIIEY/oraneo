"""Database-backed analytics, quality, exploration and run queries."""
from __future__ import annotations
import json
from typing import Any
from src.warehouse import connect

SORT_COLUMNS={'order_id','order_date','customer_id','city','product','quantity','unit_price','revenue','order_month'}

def rows(cursor): return [dict(r) for r in cursor.fetchall()]

def latest(conn):
    r=conn.execute("SELECT * FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC,id DESC LIMIT 1").fetchone()
    return dict(r) if r else None

def get_run(db:str, id:str):
    with connect(db) as c:
        r=c.execute('SELECT * FROM pipeline_runs WHERE id=?',(id,)).fetchone()
        if not r: return None
        item=dict(r);item['missing_values']=json.loads(item.pop('missing_json'))
        for key,table in [('rejection_reasons','rejected_sales'),('duplicate_reasons','duplicate_audit')]:
            records=c.execute(f'SELECT reasons_json FROM {table} WHERE run_id=?',(id,)).fetchall()
            counts={}
            for rec in records:
                for reason in json.loads(rec['reasons_json']): counts[reason]=counts.get(reason,0)+1
            item[key]=[{'name':k,'count':v} for k,v in sorted(counts.items(),key=lambda x:-x[1])]
        item['issue_frequency']=rows(c.execute('SELECT reason AS name, COUNT(*) AS count FROM quality_issues WHERE run_id=? GROUP BY reason ORDER BY count DESC',(id,)))
        return item

def run_history(db:str, page=1, page_size=20,status=None, filename=None,start_date=None,end_date=None):
    where=[];args=[]
    if status: where.append('status=?');args.append(status)
    if filename: where.append('filename LIKE ?');args.append('%'+filename+'%')
    if start_date: where.append('substr(started_at,1,10)>=?');args.append(start_date)
    if end_date: where.append('substr(started_at,1,10)<=?');args.append(end_date)
    clause='WHERE '+' AND '.join(where) if where else ''
    with connect(db) as c:
        total=c.execute('SELECT COUNT(*) FROM pipeline_runs '+clause,args).fetchone()[0]
        data=rows(c.execute(f'SELECT * FROM pipeline_runs {clause} ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?',args+[page_size,(page-1)*page_size]))
    for d in data:d.pop('missing_json',None)
    return {'items':data,'total':total,'page':page,'page_size':page_size}

def filters_sql(start_date=None,end_date=None,city=None,product=None,customer=None,search=None):
    conditions=[];params=[]
    for field,value,op in [('order_date',start_date,'>='),('order_date',end_date,'<='),('city',city,'='),('product',product,'='),('customer_id',customer,'=')]:
        if value:
            conditions.append(f'{field} {op} ?');params.append(value)
    if search:
        conditions.append('(order_id LIKE ? OR customer_id LIKE ? OR city LIKE ? OR product LIKE ?)')
        params.extend(['%'+search+'%']*4)
    return ('WHERE '+' AND '.join(conditions)) if conditions else '',params

def sales(db, page=1,page_size=20,sort_by='order_date',sort_dir='desc',**params):
    if sort_by not in SORT_COLUMNS: raise ValueError('Invalid sort field')
    if sort_dir not in ('asc','desc'): raise ValueError('Invalid sort direction')
    where,args=filters_sql(**params)
    with connect(db) as c:
        total=c.execute('SELECT COUNT(*) FROM fact_sales '+where,args).fetchone()[0]
        data=rows(c.execute(f'SELECT * FROM fact_sales {where} ORDER BY {sort_by} {sort_dir.upper()},order_id ASC LIMIT ? OFFSET ?',args+[page_size,(page-1)*page_size]))
        cities=[r[0] for r in c.execute('SELECT DISTINCT city FROM fact_sales ORDER BY city')]
        products=[r[0] for r in c.execute('SELECT DISTINCT product FROM fact_sales ORDER BY product')]
    return {'items':data,'total':total,'page':page,'page_size':page_size,'filters':{'cities':cities,'products':products}}

def analytics(db, start_date=None,end_date=None):
    where,params=filters_sql(start_date=start_date,end_date=end_date)
    with connect(db) as c:
        r=c.execute('SELECT COUNT(*) orders,COALESCE(SUM(quantity),0) units,COALESCE(SUM(revenue),0) revenue FROM fact_sales '+where,params).fetchone()
        kpi={'total_orders':r['orders'],'total_units':r['units'],'total_revenue':round(r['revenue'],2),
             'average_order_value':round(r['revenue']/r['orders'],2) if r['orders'] else 0}
        def group(by,select,order='revenue DESC',limit=None):
            sql=f'SELECT {select} FROM fact_sales {where} GROUP BY {by} ORDER BY {order}'
            if limit:sql+=f' LIMIT {int(limit)}'
            return rows(c.execute(sql,params))
        return {'kpis':kpi,
                'monthly':group('order_month','order_month AS name,ROUND(SUM(revenue),2) AS revenue,COUNT(*) AS orders','order_month ASC'),
                'cities':group('city','city AS name,ROUND(SUM(revenue),2) AS revenue,COUNT(*) AS orders'),
                'products':group('product','product AS name,ROUND(SUM(revenue),2) AS revenue,SUM(quantity) AS units'),
                'customers':group('customer_id','customer_id AS name,ROUND(SUM(revenue),2) AS revenue,COUNT(*) AS orders','revenue DESC',10)}

def quality(db,run_id=None):
    with connect(db) as c:
        if not run_id:
            last=latest(c)
            if not last:return {'run_id':None,'raw_count':0,'accepted_count':0,'rejected_count':0,'duplicate_count':0,'success_rate':0,'rejection_rate':0,'missing_values':{},'reasons':[],'issues':[]}
            run_id=last['id']
        r=c.execute('SELECT * FROM pipeline_runs WHERE id=?',(run_id,)).fetchone()
        if not r:return None
        raw=r['raw_count']
        issues=rows(c.execute('SELECT reason AS name, COUNT(*) AS count FROM quality_issues WHERE run_id=? GROUP BY reason ORDER BY count DESC',(run_id,)))
        reason_counts={}
        for x in c.execute('SELECT reasons_json FROM rejected_sales WHERE run_id=?',(run_id,)):
            for reason in json.loads(x[0]):reason_counts[reason]=reason_counts.get(reason,0)+1
        return {'run_id':run_id,'raw_count':raw,'unique_count':r['unique_count'],'accepted_count':r['accepted_count'],
                'rejected_count':r['rejected_count'],'duplicate_count':r['duplicate_count'],
                'success_rate':round(100*r['accepted_count']/raw,2) if raw else 0,
                'rejection_rate':round(100*r['rejected_count']/raw,2) if raw else 0,
                'missing_values':json.loads(r['missing_json']),
                'reasons':[{'name':a,'count':b} for a,b in sorted(reason_counts.items(),key=lambda i:-i[1])],
                'issues':issues}

def rejected(db,run_id=None,page=1,page_size=20,search='',reason='',include_duplicates=False):
    with connect(db) as c:
        if not run_id:
            last=latest(c)
            if not last:return {'items':[],'total':0,'page':page,'page_size':page_size}
            run_id=last['id']
        parts=[];args=[]
        tables=['rejected_sales']+(['duplicate_audit'] if include_duplicates else [])
        for table in tables:
            extra="disposition" if table=='duplicate_audit' else "'rejected' AS disposition"
            parts.append(f'SELECT source_row,order_id,raw_json,reasons_json,{extra} FROM {table} WHERE run_id=?')
            args.append(run_id)
        base=' UNION ALL '.join(parts)
        conditions=[];vals=[]
        if search:conditions.append('(order_id LIKE ? OR raw_json LIKE ?)');vals.extend(['%'+search+'%']*2)
        if reason:conditions.append('reasons_json LIKE ?');vals.append('%'+reason+'%')
        clause='WHERE '+' AND '.join(conditions) if conditions else ''
        count_sql=f'SELECT COUNT(*) FROM ({base}) {clause}'
        sql=f'SELECT * FROM ({base}) {clause} ORDER BY source_row LIMIT ? OFFSET ?'
        total=c.execute(count_sql,args+vals).fetchone()[0]
        items=rows(c.execute(sql,args+vals+[page_size,(page-1)*page_size]))
    for i in items:
        i['original']=json.loads(i.pop('raw_json'));i['reasons']=json.loads(i.pop('reasons_json'))
    return {'items':items,'total':total,'page':page,'page_size':page_size}

def dashboard(db):
    with connect(db) as c:
        recent=rows(c.execute('SELECT id,filename,status,started_at,duration_seconds,raw_count,accepted_count,rejected_count,duplicate_count FROM pipeline_runs ORDER BY started_at DESC LIMIT 6'))
        last=latest(c)
        runs=rows(c.execute('SELECT substr(started_at,1,16) AS name,accepted_count AS accepted,rejected_count AS rejected,duplicate_count AS duplicates FROM pipeline_runs ORDER BY started_at DESC LIMIT 15'))[::-1]
    kpis=analytics(db)['kpis']
    q=quality(db)
    with connect(db) as c:
        recent_status=c.execute('SELECT status,duration_seconds FROM pipeline_runs ORDER BY started_at DESC,id DESC LIMIT 1').fetchone()
    return {'kpis':{**kpis,'raw_count':q['raw_count'],'accepted_count':q['accepted_count'],
                    'rejected_count':q['rejected_count'],'duplicate_count':q['duplicate_count'],
                    'success_rate':q['success_rate'], 'status':recent_status['status'] if recent_status else 'no runs',
                    'duration_seconds':recent_status['duration_seconds'] if recent_status else None},
            'analytics':analytics(db),'quality':q,'recent_runs':recent,'history_chart':runs,
            'demo_data': bool(last and not last.get('input_ref')),
            'data_source': ('Bundled synthetic South African CSV' if last and not last.get('input_ref') else 'User-uploaded CSV' if last else 'No pipeline data')}
