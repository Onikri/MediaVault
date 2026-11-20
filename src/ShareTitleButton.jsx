import {useEffect,useRef,useState} from 'react';
import {Check,Link2Off,LoaderCircle,Share2} from 'lucide-react';
import {readLmt} from './LmtSettings.jsx';
import './title-share-control.css';

const translationFields=['language','directModel','directInput','font','inpaint','directDetector','directBatchPages'];

async function copyLink(link){
 if(navigator.clipboard?.write&&typeof ClipboardItem==='function'){
  const itemData=link.then(value=>new Blob([value],{type:'text/plain'}));
  itemData.catch(()=>{});
  try{
   // Request access during the click, even when the link is still being created.
   const item=new ClipboardItem({'text/plain':itemData});
   await navigator.clipboard.write([item]);
   return;
  }catch{}
 }
 const value=await link;
 await navigator.clipboard.writeText(value);
}

export default function ShareTitleButton({service,title,kind,entries=[],initial,referer,dub='',language='ru',quality='best',userId,variant='hero'}){
 const [phase,setPhase]=useState('idle'),[message,setMessage]=useState(''),[manualLink,setManualLink]=useState('');
 const root=useRef(null),cached=useRef(new Map()),last=useRef(null),working=useRef(false),restoreFocus=useRef(false);
 const reader=variant==='reader',manga=kind==='manga';
 const wide=phase!=='idle';
 const ready=service.status==='connected'&&!['guest','share'].includes(service.session?.role);
 const dismiss=()=>setPhase('idle');

 useEffect(()=>{
  if(phase==='idle')return;
  function outside(event){if(!working.current&&!root.current?.contains(event.target))dismiss();}
  document.addEventListener('pointerdown',outside);
  document.addEventListener('focusin',outside);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',outside);};
 },[phase]);
 useEffect(()=>{
  if(restoreFocus.current&&phase!=='busy'){
   const control=['copied','revoked'].includes(phase)?root.current:root.current?.querySelector(phase==='manual'?'input':'button:not(:disabled)');
   control?.focus({preventScroll:true});
   restoreFocus.current=false;
  }
  if(!['copied','revoked'].includes(phase))return;
  const timer=setTimeout(()=>{
   restoreFocus.current=root.current?.contains(document.activeElement)||false;
   dismiss();
  },phase==='copied'?4800:1800);
  return()=>clearTimeout(timer);
 },[phase]);

 async function create(translate){
  const position=Math.max(0,entries.findIndex(entry=>entry.url===initial?.url));
  const offset=position>=500?position-250:0;
  const preferences=translate?readLmt(userId):{};
  const translation=Object.fromEntries(translationFields.filter(key=>preferences[key]!==undefined).map(key=>[key,preferences[key]]));
  const body={
   title:{name:title.title||title.name,cover:title.cover||'',description:title.description||'',year:Number(title.year)||null,ids:title.ids||{}},
   kind,entries:entries.slice(offset,offset+500),initial:position-offset,referer:referer||null,dub,language,quality,translate,translation
  };
  const key=JSON.stringify([service.server,userId,body]);
  const previous=cached.current.get(translate);
  if(previous?.key===key)return previous;
  const row=await service.request('/shares/title',{method:'POST',body});
  const address=new URL(location.href);
  address.search='';
  address.hash=new URLSearchParams({share:row.token}).toString();
  const result={key,id:row.id,link:address.href,translate};
  cached.current.set(translate,result);
  return result;
 }

 async function share(translate){
  if(working.current||!ready)return;
  working.current=true;
  setPhase('busy');
  setMessage('');
  const creation=create(translate);
  const link=creation.then(row=>row.link);
  try{
   await copyLink(link);
   last.current=await creation;
   setMessage('Ссылка скопирована');
   setPhase('copied');
  }catch(error){
   const row=await creation.catch(()=>null);
   if(row){
    last.current=row;
    setManualLink(row.link);
    restoreFocus.current=true;
    setMessage('Выдели и скопируй ссылку');
    setPhase('manual');
   }else{
    last.current={translate};
    setMessage(error.message||'Не удалось создать ссылку');
    setPhase('retry');
   }
  }finally{working.current=false;}
 }

 async function revoke(){
  if(working.current||!last.current?.id)return;
  working.current=true;
  setPhase('busy');
  try{
   const row=last.current;
   await service.request('/shares/title/'+row.id,{method:'DELETE'});
   cached.current.delete(row.translate);
   last.current=null;
   setMessage('Доступ закрыт');
   setPhase('revoked');
  }catch(error){
   setMessage(error.message||'Не удалось закрыть ссылку');
   setPhase('copied');
  }finally{working.current=false;}
 }

 if(['guest','share'].includes(service.session?.role)||!entries.length)return null;
 return <span ref={root} tabIndex={-1} className="title-share-control" data-variant={variant} data-phase={phase}
  data-wide={wide||undefined} onClick={event=>event.stopPropagation()}
  onKeyDown={event=>{
   if(event.key==='Escape'&&wide&&!working.current){
    event.preventDefault();
    event.stopPropagation();
    restoreFocus.current=true;
    dismiss();
   }
  }}>
  {phase==='idle'?<button type="button" className={reader?'reader-control title-share-trigger':'circle-button title-share-trigger'}
   title="Поделиться тайтлом" aria-label="Поделиться тайтлом" disabled={!ready} aria-expanded={manga?false:undefined}
   onClick={event=>{restoreFocus.current=event.detail===0;if(manga)setPhase('choose');else share(false);}}><Share2 size={reader?19:17}/></button>:
  <span className="title-share-capsule" role={phase==='choose'?'group':undefined} aria-label={phase==='choose'?'Поделиться тайтлом':undefined} aria-busy={phase==='busy'}>
   {phase==='choose'&&<><button type="button" onClick={event=>{restoreFocus.current=event.detail===0;share(true);}}>С переводом</button><button type="button" onClick={event=>{restoreFocus.current=event.detail===0;share(false);}}>Без перевода</button></>}
   {phase==='busy'&&<span className="title-share-feedback"><LoaderCircle size={14} className="reader-translation-spinner" aria-hidden="true"/>Копируем…</span>}
   {phase==='copied'&&<><span className="title-share-feedback" title={message}><Check size={15} aria-hidden="true"/>Скопировано</span><button type="button" className="title-share-revoke" aria-label="Закрыть доступ по ссылке" title="Закрыть доступ по ссылке" onClick={revoke}><Link2Off size={15}/></button></>}
   {phase==='revoked'&&<span className="title-share-feedback"><Check size={15} aria-hidden="true"/>Доступ закрыт</span>}
   {phase==='retry'&&<button type="button" aria-label="Повторить отправку ссылки" title={message} onClick={()=>share(last.current?.translate===true)}>Повторить</button>}
   {phase==='manual'&&<><input aria-label="Ссылка на тайтл" title={message} readOnly value={manualLink} onFocus={event=>event.target.select()}/><button type="button" className="title-share-revoke" aria-label="Закрыть доступ по ссылке" title="Закрыть доступ по ссылке" onClick={revoke}><Link2Off size={15}/></button></>}
  </span>}
  <span className="sr-only" role="status">{message}</span>
 </span>;
}
