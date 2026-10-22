import React from 'react';import ReactDOM from 'react-dom/client';import {BrowserRouter,Routes,Route} from 'react-router-dom';
import {NoticeProvider} from './components/UI';import AppLayout from './layouts/AppLayout';
import Dashboard from './pages/Dashboard';import Pipeline from './pages/Pipeline';import Explorer from './pages/Explorer';import Quality from './pages/Quality';import History from './pages/History';import Reports from './pages/Reports';import Automation from './pages/Automation';import Intelligence from './pages/Intelligence';
import './styles/main.css';
import './styles/pink.css';
function App(){return <NoticeProvider><BrowserRouter><Routes><Route element={<AppLayout/>}><Route index element={<Dashboard/>}/><Route path="pipeline" element={<Pipeline/>}/><Route path="explorer" element={<Explorer/>}/><Route path="quality" element={<Quality/>}/><Route path="history" element={<History/>}/><Route path="reports" element={<Reports/>}/><Route path="automation" element={<Automation/>}/><Route path="insights" element={<Intelligence/>}/></Route></Routes></BrowserRouter></NoticeProvider>}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
