import axios, { AxiosError } from 'axios';
export const api=axios.create({baseURL:import.meta.env.VITE_API_BASE_URL||'/api/v1',timeout:30000});
export function errorText(e:unknown):string{
 if (axios.isAxiosError(e)){
  const a=e as AxiosError<{detail?:string|{msg:string}[]}>;
  if(!a.response)return 'Cannot reach ORANEO API. Start both servers with python start.py, then check /api/v1/health.';
  const d=a.response.data?.detail;
  if(typeof d==='string')return d;
  if(Array.isArray(d))return d.map(v=>v.msg).join('; ');
  if(a.response.status===500||a.response.status===503)return `Warehouse service error (HTTP ${a.response.status}). Open /api/v1/diagnostics and inspect the API terminal.`;
  if(a.response.status===401)return 'Authentication required. Reload and sign in to ORANEO.';
  return `Request failed (HTTP ${a.response.status})`;
 }
 return e instanceof Error?e.message:'Unexpected error';
}
export async function download(url:string, filename:string){
 const relative=url.startsWith('/api/v1/')?url.slice('/api/v1'.length):url;
 const result=await api.get<Blob>(relative,{responseType:'blob'});
 const object=URL.createObjectURL(result.data);
 const anchor=document.createElement('a');anchor.href=object;anchor.download=filename;
 document.body.appendChild(anchor);anchor.click();anchor.remove();window.setTimeout(()=>URL.revokeObjectURL(object),5000);
}
