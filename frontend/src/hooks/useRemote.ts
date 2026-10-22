import {useCallback,useEffect,useState} from 'react';
import {errorText} from '../api/client';
export function useRemote<T>(loader:()=>Promise<T>,deps:unknown[]){
 const [data,setData]=useState<T|null>(null);
 const [loading,setLoading]=useState(true);
 const [error,setError]=useState<string|null>(null);
 const [revision,reload]=useState(0);
 const refresh=useCallback(()=>reload(x=>x+1),[]);
 // Dependencies are intentionally passed in by the calling page.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{let cancelled=false;setLoading(true);setError(null);loader().then(value=>{if(!cancelled)setData(value)}).catch(e=>{if(!cancelled)setError(errorText(e))}).finally(()=>{if(!cancelled)setLoading(false)});return()=>{cancelled=true}},[revision,...deps]);
 return {data,loading,error,refresh};
}
