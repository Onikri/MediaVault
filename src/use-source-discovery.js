import {useEffect,useState} from 'react';
export default function useSourceDiscovery(item,service){
  const [data,setData]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();setData(null);setError('');setLoading(false);
    if(!item||item.kind!=='anime'||service.status!=='connected')return()=>controller.abort();
    setLoading(true);
    const title=Object.fromEntries(['id','ids','title','titles','aliases','year','kind','format'].map(key=>[key,item[key]]));
    service.request('/sources/discover',{method:'POST',body:{title},signal:AbortSignal.any([controller.signal,AbortSignal.timeout(90000)])})
      .then(value=>{if(!controller.signal.aborted)setData(value);})
      .catch(cause=>{if(!controller.signal.aborted)setError(cause.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[item?.id,item?.year,service.status,service.server,revision]);
  return {data,loading,error,retry:()=>setRevision(r=>r+1)};
}
