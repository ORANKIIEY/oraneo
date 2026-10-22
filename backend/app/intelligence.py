"""Explainable read-only insights derived solely from the current SQLite snapshot."""
from __future__ import annotations
from datetime import datetime, timezone
from src.warehouse import connect


def build(db: str) -> dict:
    with connect(db) as c:
        months = [dict(r) for r in c.execute('''SELECT order_month AS month,COUNT(*) AS orders,ROUND(SUM(revenue),2) AS revenue
              FROM fact_sales GROUP BY order_month ORDER BY order_month DESC LIMIT 2''')]
        total = c.execute('SELECT COUNT(*) AS orders,COALESCE(SUM(revenue),0) AS revenue FROM fact_sales').fetchone()
        top_city = c.execute('''SELECT city AS name,COUNT(*) AS orders,ROUND(SUM(revenue),2) AS revenue
                    FROM fact_sales GROUP BY city ORDER BY revenue DESC,city LIMIT 1''').fetchone()
        top_product = c.execute('''SELECT product AS name,SUM(quantity) AS units,ROUND(SUM(revenue),2) AS revenue
                    FROM fact_sales GROUP BY product ORDER BY revenue DESC,product LIMIT 1''').fetchone()
        last = c.execute('''SELECT id,input_ref,started_at,finished_at,status,raw_count,accepted_count,rejected_count,
                    duplicate_count FROM pipeline_runs WHERE status='success' ORDER BY finished_at DESC,id DESC LIMIT 1''').fetchone()
        active_run = c.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='running'").fetchone()[0]
    current = months[0] if months else None
    previous = months[1] if len(months) > 1 else None
    delta = None
    if current and previous and previous['revenue']:
        delta = round((current['revenue'] - previous['revenue']) / previous['revenue'] * 100, 2)
    revenue = total['revenue'] or 0
    def share(item):return round(100*item['revenue']/revenue,2) if item and revenue else 0
    freshness = None
    if last and last['finished_at']:
        finished = datetime.fromisoformat(last['finished_at'])
        freshness = round(max(0,(datetime.now(timezone.utc)-finished).total_seconds())/3600,1)
    signals = []
    if not current:
        signals.append({'level':'neutral','title':'No sales snapshot yet','explanation':'Run the pipeline to populate the warehouse. No trend can be inferred.'})
    if current and previous:
        signals.append({'level':'positive' if delta is not None and delta>=0 else 'warning',
                        'title':'Revenue change across available months',
                        'explanation':f'{current["month"]} compared with {previous["month"]}: {delta:+.2f}% revenue. This is a comparison of available calendar months, not a seasonally adjusted forecast.'})
    elif current:
        signals.append({'level':'neutral','title':'Insufficient monthly history',
                        'explanation':f'The snapshot has data for {current["month"]}, but a second month is needed for a comparison.'})
    if top_city:
        signals.append({'level':'neutral','title':'Leading city by revenue',
                        'explanation':f'{top_city["name"]} contributes {share(top_city):.2f}% of sales revenue in the current snapshot.'})
    if last and last['raw_count']:
        rate = 100 * last['rejected_count']/last['raw_count']
        signals.append({'level':'warning' if rate > 5 else 'positive', 'title':'Latest run quality',
                        'explanation':f'{last["rejected_count"]} of {last["raw_count"]} input rows rejected ({rate:.2f}%). Duplicate rows are tracked separately.'})
    return {'current_month':current,'previous_month':previous,'revenue_change_pct':delta,
            'top_city':dict(top_city) if top_city else None,'top_city_share_pct':share(top_city),
            'top_product':dict(top_product) if top_product else None,'top_product_share_pct':share(top_product),
            'last_successful_run':dict(last) if last else None,'freshness_hours':freshness,
            'pipeline_running':bool(active_run),'data_origin':('Bundled synthetic sample' if last and not last['input_ref'] else 'User-uploaded CSV' if last else 'No data'), 'total_orders':total['orders'],'total_revenue':round(revenue,2),
            'signals':signals,'methodology':'Snapshot-based and descriptive only; no external data, forecasts or fabricated insights.'}
