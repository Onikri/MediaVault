import {useEffect,useState} from 'react';

// One observer per shelf; only cards near the viewport enter the work queue.
export default function useVisibleCards(root,signature){
 const [visible,setVisible]=useState(()=>new Set());
 useEffect(()=>{
  const values=new Set(),publish=()=>setVisible(old=>old.size===values.size&&[...values].every(v=>old.has(v))?old:new Set(values));
  setVisible(new Set());
  const observer=new IntersectionObserver(entries=>{for(const entry of entries){const key=entry.target.dataset.previewKey;if(entry.isIntersecting)values.add(key);else values.delete(key);}publish();},{rootMargin:'160px'});
  root.current?.querySelectorAll('[data-preview-key]').forEach(node=>observer.observe(node));
  return()=>observer.disconnect();
 },[root,signature]);
 return visible;
}
