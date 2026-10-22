"""Native-text multi-page PDF reporting using ReportLab Platypus."""
from __future__ import annotations
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import html
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Line, PolyLine, String, Rect
from backend.app.service import analytics,quality,run_history,dashboard

NAVY=colors.HexColor('#1d2629')
BLUE=colors.HexColor('#d9367e')
GRAY=colors.HexColor('#58666a')


def produce(db: str, kind: str='sales',start_date: str|None=None,end_date: str|None=None,currency: str='ZAR') -> bytes:
    if kind not in ('sales','quality','pipeline','filtered'):raise ValueError('Unsupported report type')
    a=analytics(db,start_date,end_date)
    q=quality(db)
    history=run_history(db,page_size=100)['items']
    source=dashboard(db)['data_source']
    buffer=BytesIO()
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='HeroCustom',parent=styles['Title'],fontName='Helvetica-Bold',fontSize=19,leading=24,textColor=NAVY,spaceAfter=12))
    styles.add(ParagraphStyle(name='SectionCustom',parent=styles['Heading2'],fontSize=12,leading=16,textColor=NAVY,spaceBefore=14,spaceAfter=7))
    styles.add(ParagraphStyle(name='BodyCustom',parent=styles['BodyText'],fontSize=9,leading=14,spaceAfter=8))
    styles.add(ParagraphStyle(name='CellCustom',parent=styles['BodyText'],fontSize=7.3,leading=10))
    styles.add(ParagraphStyle(name='HeadCellCustom',parent=styles['CellCustom'],fontName='Helvetica-Bold',textColor=colors.white))
    doc=SimpleDocTemplate(buffer,pagesize=(210*mm,297*mm),rightMargin=19*mm,leftMargin=19*mm,topMargin=19*mm,bottomMargin=21*mm,
                          title='ORANEO South Africa Report',author='ORANEO ETL')
    story=[]
    def p(s,style='BodyCustom'):return Paragraph(html.escape(str(s)),styles[style])
    def heading(s):story.append(p(s,'SectionCustom'))
    def paragraph(s):story.append(p(s))
    def table(header, data, widths=None):
        data=list(data)
        if not data:paragraph('No records match the selected filters.');return
        cells=[[p(h,'HeadCellCustom') for h in header]]+[[p(v,'CellCustom') for v in record] for record in data]
        t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),NAVY),('TEXTCOLOR',(0,0),(-1,0),colors.white),
                              ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.whitesmoke,colors.white]),
                              ('GRID',(0,0),(-1,-1),.25,colors.HexColor('#d5dfe7')),
                              ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),
                              ('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.append(t)
    def money(v):return f'{currency + " " if currency else ""}{float(v):,.2f}'
    titles={'sales':'Full Sales Analytics Report','quality':'Data Quality Audit Report',
            'pipeline':'Pipeline Execution Report','filtered':'Date-Filtered Sales Report'}
    story.append(p(titles[kind],'HeroCustom'))
    paragraph('ORANEO / South Africa  |  Generated '+datetime.now(timezone.utc).strftime('%d %B %Y %H:%M UTC'))
    paragraph(f'Report period: {start_date or "All dates"} to {end_date or "All dates"}. Currency: {currency or "Not specified"}.')
    heading('Executive summary')
    if kind in ('sales','filtered'):
        paragraph(f"The warehouse contains {a['kpis']['total_orders']:,} orders in the selected period, "
                  f"with total revenue of {money(a['kpis']['total_revenue'])} and {a['kpis']['total_units']:,} units sold.")
        heading('Key performance indicators')
        table(['Measure','Value'],[['Total revenue',money(a['kpis']['total_revenue'])],['Total orders',a['kpis']['total_orders']],
                                   ['Units sold',a['kpis']['total_units']],['Average order value',money(a['kpis']['average_order_value'])]],[95*mm,77*mm])
        heading('Monthly revenue trend')
        if a['monthly']:
            chart=Drawing(172*mm,47*mm)
            left,right,bottom,top=16*mm,167*mm,11*mm,40*mm
            chart.add(Line(left,bottom,right,bottom,strokeColor=colors.HexColor('#b7cbd5'),strokeWidth=.8))
            chart.add(Line(left,bottom,left,top,strokeColor=colors.HexColor('#b7cbd5'),strokeWidth=.8))
            values=[float(r['revenue']) for r in a['monthly']]
            maximum=max(values) or 1
            coords=[(left+(right-left)*(i/max(1,len(values)-1)),bottom+(top-bottom)*v/maximum) for i,v in enumerate(values)]
            if len(coords)>1: chart.add(PolyLine([k for x,y in coords for k in (x,y)],strokeColor=BLUE,strokeWidth=2.4))
            for (x,y),entry in zip(coords,a['monthly']):
                chart.add(Rect(x-2.5,y-2.5,5,5,strokeColor=colors.white,fillColor=BLUE,strokeWidth=.5))
                chart.add(String(x,bottom-8,entry['name'][5:],fontName='Helvetica',fontSize=7,fillColor=GRAY,textAnchor='middle'))
            chart.add(String(left,top+8,f'Max {money(maximum)}',fontName='Helvetica',fontSize=8,fillColor=GRAY))
            story.append(chart)
        table(['Month','Revenue','Orders'],[[r['name'],money(r['revenue']),r['orders']] for r in a['monthly']],[55*mm,70*mm,47*mm])
        heading('Revenue by city')
        table(['City','Revenue','Orders'],[[r['name'],money(r['revenue']),r['orders']] for r in a['cities']],[55*mm,70*mm,47*mm])
        heading('Revenue and units by product')
        table(['Product','Revenue','Units'],[[r['name'],money(r['revenue']),r['units']] for r in a['products']],[55*mm,70*mm,47*mm])
        heading('Top customers')
        table(['Customer','Revenue','Orders'],[[r['name'],money(r['revenue']),r['orders']] for r in a['customers']],[55*mm,70*mm,47*mm])
    if kind in ('sales','quality','pipeline'):
        if kind!='sales':paragraph(f"In the latest successful run, {q['raw_count']} raw rows were audited, "
                                    f"including {q['rejected_count']} rejected rows and {q['duplicate_count']} duplicates.")
        heading('Data quality summary')
        table(['Measure','Count'],[['Raw input rows',q['raw_count']],['Unique records',q.get('unique_count',0)],
                                   ['Accepted',q['accepted_count']],['Rejected unique rows',q['rejected_count']],
                                   ['Duplicate rows',q['duplicate_count']],['Acceptance rate',f"{q['success_rate']:.2f}%"]],[95*mm,77*mm])
        heading('Rejection reasons')
        table(['Reason','Occurrences'],[[v['name'],v['count']] for v in q['reasons']],[122*mm,50*mm])
        heading('Missing values by column')
        table(['Column','Rows missing'],q['missing_values'].items(),[110*mm,62*mm])
    if kind in ('sales','pipeline'):
        heading('Pipeline execution summary')
        table(['Run ID','Status','Raw','Accepted','Rejected','Duplicates'],
              [[r['id'][:8],r['status'],r['raw_count'],r['accepted_count'],r['rejected_count'],r['duplicate_count']]
               for r in history],[30*mm,29*mm,26*mm,30*mm,29*mm,28*mm])
    heading('Methodology and limitations')
    paragraph('Revenue = quantity x unit price. One valid row per order ID is retained, prioritising the earliest valid occurrence. ' 
              'Additional occurrences are kept in the duplicate audit. Snapshots replace the active sales fact table on successful runs; historical run audits remain available.')
    paragraph(f'Current snapshot source: {source}. Bundled South African records are synthetic demonstrations, not measured real-world sales. '
              'Uploaded datasets are assumed to use the configured currency; currency is never inferred from CSV fields.')
    def footer(canvas,d):
        canvas.saveState();canvas.setStrokeColor(colors.HexColor('#dce5ee'))
        canvas.line(19*mm,17*mm,191*mm,17*mm)
        canvas.setFont('Helvetica',8);canvas.setFillColor(GRAY)
        canvas.drawString(19*mm,12.5*mm, f'ORANEO · {source[:54]} · {currency or "Currency unspecified"}')
        canvas.drawRightString(191*mm,12.5*mm,f'Page {d.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
