import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
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
 const root=useRef(null),trigger=useRef(null),menu=useRef(null),cached=useRef(new Map()),last=useRef(null),working=useRef(false);
 const menuId=useId(),reader=variant==='reader',manga=kind==='manga'&&entries.length>0;
 const wide=phase!=='idle';
 const ready=service?.status==='connected'&&!['guest','share'].includes(service.session?.role);
 const dismiss=(focus=false)=>{if(focus)trigger.current?.focus({preventScroll:true});setPhase('idle');};
 const [portal,setPortal]=useState(null);

 useLayoutEffect(()=>{
  if(!wide)return;
  const host=()=>setPortal(document.fullscreenElement||document.body);
  host();
  document.addEventListener('fullscreenchange',host);
  return()=>document.removeEventListener('fullscreenchange',host);
 },[wide]);
 useLayoutEffect(()=>{
  if(!wide||!portal)return;
  const place=()=>{
   const anchor=trigger.current?.getBoundingClientRect(),node=menu.current;
   if(!anchor||!node)return;
   const above=anchor.bottom+node.offsetHeight+12>document.documentElement.clientHeight;
   node.style.left=Math.max(8,Math.min(anchor.left+(anchor.width-node.offsetWidth)/2,document.documentElement.clientWidth-node.offsetWidth-8))+'px';
   node.style.top=Math.max(8,above?anchor.top-node.offsetHeight-7:anchor.bottom+7)+'px';
   node.dataset.above=String(above);
  };
  place();
  window.addEventListener('resize',place);
  window.addEventListener('scroll',place,true);
  if(phase==='manual')menu.current?.querySelector('input')?.focus({preventScroll:true});
  else if(phase==='choose')menu.current?.querySelector('button')?.focus({preventScroll:true});
  return()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
 },[wide,portal,phase]);

 useEffect(()=>{
  if(phase==='idle')return;
  const outside=event=>{if(!working.current&&!root.current?.contains(event.target)&&!menu.current?.contains(event.target))dismiss();};
  const escape=event=>{
   if(event.key!=='Escape'||working.current)return;
   event.preventDefault();
   event.stopPropagation();
   dismiss(menu.current?.contains(document.activeElement));
  };
  document.addEventListener('pointerdown',outside,true);
  window.addEventListener('keydown',escape,true);
  return()=>{document.removeEventListener('pointerdown',outside,true);window.removeEventListener('keydown',escape,true);};
 },[wide]);
 useEffect(()=>{
  if(!['copied','revoked'].includes(phase))return;
  const timer=setTimeout(()=>dismiss(menu.current?.contains(document.activeElement)),phase==='copied'?4800:1800);
  return()=>clearTimeout(timer);
 },[phase]);

 async function create(translate){
  const position=Math.max(0,entries.findIndex(entry=>entry.url===initial?.url));
  const offset=position>=500?position-250:0;
  const preferences=translate?readLmt(userId):{};
  const translation=Object.fromEntries(translationFields.filter(key=>preferences[key]!==undefined).map(key=>[key,preferences[key]]));
  const body={
   title:{name:title.title||title.name,cover:/^https?:\/\//i.test(title.cover||'')?title.cover:'',description:title.description||'',year:Number(title.year)||null,ids:title.ids||{},
    format:String(title.format||'').slice(0,120),section:title.section||'',readingMode:['scroll','pages'].includes(title.readingMode)?title.readingMode:''},
   kind:entries.length?kind:'title',entries:entries.slice(offset,offset+500),initial:position-offset,referer:entries.length&&referer?referer:null,dub,language,quality,translate,translation
  };
  const key=JSON.stringify([service.server,userId,body]);
  const previous=cached.current.get(translate);
  if(previous?.key===key)return previous;
  const row=await service.request('/shares/title',{method:'POST',body});
  const address=new URL(location.href);
  address.search='';
  address.hash=new URLSearchParams({share:row.token}).toString();
  const result={key,id:row.id,link:address.href,translate,card:!entries.length};
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
   // Without chosen episodes or chapters the guest gets only the card: say so.
   setMessage(last.current.card?'Скопирована ссылка только на карточку: серии и главы ещё не выбраны':'Ссылка скопирована');
   setPhase('copied');
  }catch(error){
   const row=await creation.catch(()=>null);
   if(row){
    last.current=row;
    setManualLink(row.link);
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

 if(['guest','share'].includes(service?.session?.role))return null;
 return <span ref={root} className="title-share-control" data-variant={variant} data-phase={phase} onClick={event=>event.stopPropagation()}>
  <button ref={trigger} type="button" className={reader?'reader-control title-share-trigger':'circle-button title-share-trigger'}
   title={ready?'Поделиться тайтлом':'Подключаемся к серверу'} aria-label="Поделиться тайтлом" disabled={!ready}
   aria-expanded={wide} aria-controls={wide?menuId:undefined}
   onClick={()=>{if(working.current)return;if(wide)dismiss();else if(manga)setPhase('choose');else share(false);}}><Share2 size={reader?19:17}/></button>
  {wide&&portal&&createPortal(<span ref={menu} id={menuId} className="title-share-capsule" data-phase={phase}
   role="group" aria-label="Варианты ссылки" aria-busy={phase==='busy'}>
   {phase==='choose'&&<><button type="button" onClick={()=>share(true)}>С переводом</button><button type="button" onClick={()=>share(false)}>Без перевода</button></>}
   {phase==='busy'&&<span className="title-share-feedback"><LoaderCircle size={14} className="reader-translation-spinner" aria-hidden="true"/>Копируем…</span>}
   {phase==='copied'&&<><span className="title-share-feedback" title={message}><Check size={15} aria-hidden="true"/>{last.current?.card?'Только карточка':'Скопировано'}</span><button type="button" className="title-share-revoke" aria-label="Закрыть доступ по ссылке" title="Закрыть доступ по ссылке" onClick={revoke}><Link2Off size={15}/></button></>}
   {phase==='revoked'&&<span className="title-share-feedback"><Check size={15} aria-hidden="true"/>Доступ закрыт</span>}
   {phase==='retry'&&<button type="button" aria-label="Повторить отправку ссылки" title={message} onClick={()=>share(last.current?.translate===true)}>Повторить</button>}
   {phase==='manual'&&<><input aria-label="Ссылка на тайтл" title={message} readOnly value={manualLink} onFocus={event=>event.target.select()}/><button type="button" className="title-share-revoke" aria-label="Закрыть доступ по ссылке" title="Закрыть доступ по ссылке" onClick={revoke}><Link2Off size={15}/></button></>}
  </span>,portal)}
  <span className="sr-only" role="status">{message}</span>
 </span>;
}
