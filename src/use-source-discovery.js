import {useEffect,useState} from 'react';
export default function useSourceDiscovery(item,service){
  const [data,setData]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();setData(null);setError('');setLoading(false);
    if(!item||item.kind!=='anime'||(!service.session?.serverVersion&&service.status!=='connected'))return()=>controller.abort();
    if(service.session?.serverVersion&&service.session.serverVersion<7){setError('Сервер импорта нужно обновить для полного списка озвучек и качеств.');return()=>controller.abort();}
    setLoading(true);
    const title=Object.fromEntries(['id','ids','title','titles','aliases','year','kind','format'].map(key=>[key,item[key]]));
    const search=async()=>{
      let value,continuing=false,previousProgress=-1,stalled=0;
      do{
        value=await service.request('/sources/discover',{method:'POST',body:{title,refresh:revision>0||continuing,continuing},signal:AbortSignal.any([controller.signal,AbortSignal.timeout(90000)])});
        if(controller.signal.aborted)return;
        setData(old=>{if(!old)return value;const sources=[...new Map([...(old.sources||[]),...(value.sources||[])].map(s=>[s.url,s])).values()],voices=new Map((old.voices||[]).map(v=>[v.id,v]));for(const v of value.voices||[]){const before=voices.get(v.id);voices.set(v.id,before?{...v,variants:[...new Map([...before.variants,...v.variants].map(r=>[r.id,r])).values()]}:v);}return {...value,sources,voices:[...voices.values()]};});continuing=!!value.pending;
        stalled=continuing&&value.progress===previousProgress?stalled+1:0;previousProgress=value.progress;
        if(stalled>=3)throw Error('Часть источников перестала отвечать. Найденные переводы сохранены; можно повторить проверку позже.');
      }while(continuing);
    };
    search()
      .catch(cause=>{if(!controller.signal.aborted)setError(cause.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[item?.id,item?.year,service.server,service.session?.serverVersion||service.status==='connected',revision]);
  return {data,loading,error,retry:()=>setRevision(r=>r+1)};
}
