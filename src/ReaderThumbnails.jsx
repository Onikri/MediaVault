import {useEffect,useRef,useState} from 'react';
function Thumb({entry,index,current,onChoose}){
 const host=useRef(null),[source,setSource]=useState(''),[near,setNear]=useState(false);
 useEffect(()=>{const o=new IntersectionObserver(e=>setNear(e.some(v=>v.isIntersecting)),{rootMargin:'100px'});o.observe(host.current);return()=>o.disconnect();},[]);
 useEffect(()=>{if(!near)return;let closed=false,url;entry.async('blob').then(async blob=>{const bitmap=await createImageBitmap(blob);if(closed){bitmap.close();return;}const c=document.createElement('canvas');c.width=112;c.height=Math.max(1,Math.round(112*bitmap.height/bitmap.width));if(c.height>800)c.height=800;c.getContext('2d').drawImage(bitmap,0,0,c.width,c.height);bitmap.close();c.toBlob(b=>{if(!b||closed)return;url=URL.createObjectURL(b);setSource(url);},'image/webp',.65);}).catch(()=>{});return()=>{closed=true;if(url)URL.revokeObjectURL(url);};},[entry,near]);
 return <button ref={host} type="button" aria-label={'Перейти к странице '+(index+1)} aria-current={current} onClick={onChoose}>{source?<img src={source} alt=""/>:<div className="reader-filmstrip-placeholder">{index+1}</div>}<small>{index+1}</small></button>;
}
export default function ReaderThumbnails({entries,page,onChoose}){return <nav className="reader-filmstrip" aria-label="Превью страниц">{entries.map((entry,i)=><Thumb key={entry.name+':'+i} entry={entry} index={i} current={i===page} onChoose={()=>onChoose(i)}/>)}</nav>;}
