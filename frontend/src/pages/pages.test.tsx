import {beforeEach,describe,expect,it,vi} from 'vitest';
import type {ReactElement} from 'react';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import Dashboard from './Dashboard';
import Explorer from './Explorer';
import Reports from './Reports';
import Pipeline from './Pipeline';
import {api,download} from '../api/client';

vi.mock('../api/client',()=>({api:{get:vi.fn(),post:vi.fn(),put:vi.fn()},download:vi.fn(),errorText:(err:Error)=>err.message}));
vi.mock('../components/Charts',()=>({RevenueArea:()=> <div>Revenue chart</div>,HorizontalBar:()=> <div>Comparison chart</div>,RunBar:()=> <div>Run chart</div>}));
const dashboard={currency:'ZAR',demo_data:true,
 kpis:{total_revenue:1000,total_orders:2,total_units:3,average_order_value:500,raw_count:3,accepted_count:2,rejected_count:1,duplicate_count:0,success_rate:66.67,status:'success',duration_seconds:1},
 analytics:{monthly:[{name:'2026-01',revenue:1000}],cities:[{name:'Durban',revenue:1000}],products:[{name:'Mouse',revenue:1000,units:3}],customers:[{name:'ZA0001',revenue:1000}]},
 recent_runs:[],history_chart:[]};
const sale={order_id:'ZA100',order_date:'2026-10-01',customer_id:'ZA0001',city:'Durban',product:'Mouse',quantity:2,unit_price:50,revenue:100,order_month:'2026-10'};
const preview={kind:'sales',period:{start_date:null,end_date:null},currency:'ZAR',kpis:{total_revenue:1500,total_orders:3,total_units:5,average_order_value:500},quality:{rejected_count:2},recent_runs:[]};
const success=(data:unknown):Promise<never>=>Promise.resolve({data} as never);
const renderPage=(page:ReactElement)=>render(<MemoryRouter>{page}</MemoryRouter>);

beforeEach(()=>{vi.clearAllMocks()});

describe('Overview',()=>{
 it('loads real API response metrics',async()=>{
  vi.mocked(api.get).mockResolvedValue({data:dashboard} as never);
  renderPage(<Dashboard/>);
  expect(await screen.findByText(text=>text.replace(/\s/g,'').includes('1000,00'))).toBeInTheDocument();
  expect(screen.getByText('Revenue chart')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/dashboard');
 });
 it('shows a useful backend error',async()=>{
  vi.mocked(api.get).mockRejectedValue(new Error('Backend unavailable'));
  renderPage(<Dashboard/>);
  expect(await screen.findByText('Backend unavailable')).toBeInTheDocument();
 });
});

describe('Sales explorer',()=>{
 it('sends filters to the backend rather than filtering local rows',async()=>{
  vi.mocked(api.get).mockImplementation(()=>success({items:[sale],total:1,page:1,page_size:20,filters:{cities:['Durban'],products:['Mouse']}}));
  renderPage(<Explorer/>);
  expect(await screen.findByText('ZA100')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Search sales'),{target:{value:'ZA100'}});
  fireEvent.click(screen.getByRole('button',{name:'Search'}));
  await waitFor(()=>expect(api.get).toHaveBeenLastCalledWith('/sales',expect.objectContaining({params:expect.objectContaining({search:'ZA100'})})));
 });
});

describe('Reports',()=>{
 it('calls report API and downloads the generated PDF',async()=>{
  vi.mocked(api.get).mockImplementation(()=>success(preview));
  vi.mocked(api.post).mockImplementation(()=>success({filename:'report.pdf',download_url:'/api/v1/reports/abc/download'}));
  vi.mocked(download).mockResolvedValue(undefined);
  renderPage(<Reports/>);
  expect(await screen.findByText(text=>text.replace(/\s/g,'').includes('1500,00'))).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/Generate & download PDF/}));
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/reports',expect.objectContaining({kind:'sales'})));
  await waitFor(()=>expect(download).toHaveBeenCalledWith('/api/v1/reports/abc/download','report.pdf'));
 });
});

describe('Pipeline control',()=>{
 it('starts a pipeline and shows its completed counts',async()=>{
  vi.mocked(api.get).mockImplementation((url)=>{
   if(url==='/runs')return success({items:[],total:0,page:1,page_size:7});
   if(url==='/inputs/default/preview')return success({filename:'sales_raw.csv',raw_count:100,unique_count:95,accepted_count:90,rejected_count:5,duplicate_count:5,missing_values:{}});
   return success({id:'abc',status:'success',filename:'sales_raw.csv',started_at:'2026-10-21T10:00:00Z',finished_at:'2026-10-21T10:01:00Z',raw_count:100,unique_count:95,accepted_count:90,rejected_count:5,duplicate_count:5,duration_seconds:60,log:'Completed',error:null});
  });
  vi.mocked(api.post).mockImplementation(()=>success({run_id:'abc'}));
  renderPage(<Pipeline/>);
  fireEvent.click(screen.getByRole('button',{name:/Execute pipeline/}));
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/runs',{}));
  expect(await screen.findByText('Processing log')).toBeInTheDocument();
 });
});

describe('ORANEO automation',()=>{
 it('persists recurring schedule settings through the API',async()=>{
  const Automation=(await import('./Automation')).default;
  const settings={enabled:false,interval_minutes:1440,rejection_threshold:5,duplicate_threshold:3,next_run_at:null,last_triggered_at:null,updated_at:'2026-10-21',schedule_scope:'local_api_process'};
  vi.mocked(api.get).mockImplementation(()=>success({settings,alerts:{items:[],unread:0}}));
  vi.mocked(api.put).mockImplementation(()=>success({...settings,enabled:true}));
  renderPage(<Automation/>);
  expect(await screen.findByText('No open exceptions')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:/Save automation rules/}));
  await waitFor(()=>expect(api.put).toHaveBeenCalledWith('/automation',expect.objectContaining({enabled:true})));
 });
});

describe('ORANEO intelligence',()=>{
 it('explains warehouse values returned from the API',async()=>{
  const Intelligence=(await import('./Intelligence')).default;
  vi.mocked(api.get).mockImplementation(()=>success({currency:'ZAR',data_origin:'Bundled synthetic sample',total_orders:2,total_revenue:1000,
   current_month:{month:'2026-10',revenue:1000,orders:2},previous_month:{month:'2026-09',revenue:500,orders:1},revenue_change_pct:100,
   top_city:{name:'Durban',orders:2,revenue:1000},top_city_share_pct:100,top_product:{name:'Mouse',units:3,revenue:1000},top_product_share_pct:100,
   last_successful_run:null,freshness_hours:null,pipeline_running:false,signals:[{level:'neutral',title:'Source verified',explanation:'Data comes from the current snapshot.'}],methodology:'Descriptive only.'}));
  renderPage(<Intelligence/>);
  expect(await screen.findByText('Source verified')).toBeInTheDocument();
  expect(screen.getByText('Metric definitions')).toBeInTheDocument();
 });
});
