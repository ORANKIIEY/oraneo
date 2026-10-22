import {NavLink,Outlet,useLocation,useNavigate} from 'react-router-dom';
import {Activity,BarChart3,Bell,BookOpen,ChevronRight,Command,Database,FileText,History,Layers3,Menu,Search,Settings2,ShieldCheck,X} from 'lucide-react';
import {useEffect,useRef,useState} from 'react';
import {api} from '../api/client';
import {ErrorBoundary} from '../components/ErrorBoundary';

const nav=[
 {to:'/',label:'Overview',icon:BarChart3,group:'Monitor',hint:'Performance and activity'},
 {to:'/insights',label:'Warehouse insights',icon:BookOpen,group:'Monitor',hint:'Explain trends and changes'},
 {to:'/pipeline',label:'Pipeline control',icon:Layers3,group:'Operate',hint:'Run and validate a CSV'},
 {to:'/automation',label:'Automation & alerts',icon:Settings2,group:'Operate',hint:'Schedules and guardrails'},
 {to:'/explorer',label:'Sales explorer',icon:Database,group:'Explore',hint:'Search accepted rows'},
 {to:'/quality',label:'Data quality',icon:ShieldCheck,group:'Explore',hint:'Rejections and duplicates'},
 {to:'/history',label:'Run history',icon:History,group:'Explore',hint:'Execution logs'},
 {to:'/reports',label:'Reports centre',icon:FileText,group:'Explore',hint:'Generate native PDF reports'}
];
export default function AppLayout(){
 const [open,setOpen]=useState(false);const [palette,setPalette]=useState(false);const [query,setQuery]=useState('');const [pending,setPending]=useState(0);
 const searchRef=useRef<HTMLInputElement>(null);const location=useLocation();const navigate=useNavigate();
 useEffect(()=>{setOpen(false);setPalette(false)},[location]);
 useEffect(()=>{if(palette)searchRef.current?.focus()},[palette]);
 useEffect(()=>{function onKey(e:KeyboardEvent){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setPalette(x=>!x)}if(e.key==='Escape'){setPalette(false);setOpen(false)}}window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[]);
 useEffect(()=>{let mounted=true;const refresh=()=>{api.get<{unread:number}>('/alerts',{params:{limit:1}}).then(r=>{if(mounted)setPending(r.data.unread)}).catch(()=>{})};refresh();const id=setInterval(refresh,45000);return()=>{mounted=false;clearInterval(id)}},[location]);
 const current=nav.find(n=>n.to===location.pathname)?.label||'Overview';
 const filtered=nav.filter(n=>(n.label+' '+n.hint).toLowerCase().includes(query.toLowerCase()));
 function go(to:string){setPalette(false);setQuery('');navigate(to)}
 return <div className="app-shell">
 <button className={'sidebar-overlay '+(open?'visible':'')} aria-label="Close navigation" onClick={()=>setOpen(false)}></button>
 <aside className={'sidebar '+(open?'open':'')}>
  <div className="brand"><div className="wordmark"><strong>ORANEO</strong><span>DATA OPERATIONS</span></div><button className="mobile-close" onClick={()=>setOpen(false)} aria-label="Close menu"><X size={21}/></button></div>
  <div className="workspace-card"><div className="workspace-card-top"><span className="active-square"/> SA WORKSPACE</div><strong>Revenue operations</strong><span>Synthetic sample · ZAR</span></div>
  <nav className="side-nav" aria-label="Primary navigation">{['Monitor','Operate','Explore'].map(group=><div className="nav-group" key={group}><div className="nav-section-label">{group.toUpperCase()}</div>{nav.filter(n=>n.group===group).map(item=><NavLink end={item.to==='/'} key={item.to} to={item.to} className={({isActive})=>'nav-link '+(isActive?'active':'')}><item.icon size={17}/><span>{item.label}</span>{item.to==='/automation'&&pending>0?<span className="nav-count">{pending}</span>:null}</NavLink>)}</div>)}</nav>
  <button className="sidebar-search" onClick={()=>setPalette(true)}><Search size={16}/> Quick navigation <kbd>Ctrl K</kbd></button>
  <div className="sidebar-footer"><span className="live-square"/><div><strong>Data workspace</strong><span>Python / SQLite / FastAPI</span></div></div>
 </aside>
 <div className="main-area"><header className="topbar"><div className="topbar-left"><button className="menu-toggle" aria-label="Open navigation" onClick={()=>setOpen(true)}><Menu size={20}/></button><span className="topbar-breadcrumb">ORANEO</span><ChevronRight size={13}/><b>{current}</b></div><div className="topbar-right"><span className="environment-pill"><span/> DATA WORKSPACE</span><button className="top-icon-button" title="Quick navigation (Ctrl+K)" aria-label="Open command menu" onClick={()=>setPalette(true)}><Command size={17}/></button><NavLink to="/automation" className="top-icon-button alert-link" aria-label={`View alerts (${pending} unread)`}><Bell size={18}/>{pending>0&&<span className="alert-bubble">{pending}</span>}</NavLink><a className="help-link" title="OpenAPI documentation" target="_blank" rel="noreferrer" href="/docs"><Activity size={16}/> API</a></div></header>
 <main className="page-content"><ErrorBoundary key={location.pathname}><Outlet/></ErrorBoundary></main><footer className="app-footer"><span>ORANEO / DATA OPERATIONS</span><span>South African synthetic demonstration data. Metrics originate in SQLite.</span><span>2026</span></footer></div>
 {palette&&<div className="palette-overlay" role="presentation" onMouseDown={()=>setPalette(false)}><div className="command-dialog" role="dialog" aria-modal="true" aria-label="Quick navigation" onMouseDown={e=>e.stopPropagation()}><div className="command-field"><Search size={20}/><input ref={searchRef} value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&filtered.length)go(filtered[0].to)}} placeholder="Jump to a workspace page…" aria-label="Search pages"/><button onClick={()=>setPalette(false)} aria-label="Close quick navigation"><X size={18}/></button></div><div className="command-items">{filtered.length?filtered.map(n=><button key={n.to} onClick={()=>go(n.to)} className="command-result"><n.icon size={19}/><span><strong>{n.label}</strong><small>{n.hint}</small></span><ChevronRight size={16}/></button>):<div className="command-empty">No matching pages</div>}</div><div className="command-footer">ESC to close <span>ENTER to open first result</span></div></div></div>}
 </div>
}
