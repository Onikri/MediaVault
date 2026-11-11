import {useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {Check,Copy,Share2,X} from 'lucide-react';
import {readLmt} from './LmtSettings.jsx';

export default function ShareTitleButton({service,title,kind,entries=[],initial,referer,dub='',language='ru',quality='best',userId}){
 const [open,setOpen]=useState(false),[link,setLink]=useState(''),[identity,setIdentity]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[copied,setCopied]=useState(false);
 const [translate,setTranslate]=useState(kind==='manga'&&language!=='ru');
 if(service.session?.role==='guest'||service.session?.role==='share'||!entries.length)return null;
 async function create(){
  setBusy(true);setError('');
  try{
   const position=Math.max(0,entries.findIndex(e=>e.url===initial?.url));
   const offset=position>=500?Math.max(0,position-250):0;
   const row=await service.request('/shares/title',{method:'POST',body:{
    title:{name:title.title||title.name,cover:title.cover||'',description:title.description||'',year:Number(title.year)||null,ids:title.ids||{}},
    kind,entries:entries.slice(offset,offset+500),initial:position-offset,referer:referer||null,dub,language,quality,
    translate,translation:kind==='manga'?readLmt(userId):{}
   }});
   const address=new URL(location.href);address.search='';address.hash=new URLSearchParams({share:row.token}).toString();
   setLink(address.href);setIdentity(row.id);setCopied(false);
  }catch(e){setError(e.message);}finally{setBusy(false);}
 }
 async function copy(){try{await navigator.clipboard.writeText(link);setCopied(true);}catch{setError('Выдели и скопируй ссылку из поля.');}}
 async function revoke(){
  setBusy(true);
  try{await service.request('/shares/title/'+identity,{method:'DELETE'});setLink('');setIdentity('');}
  catch(e){setError(e.message);}finally{setBusy(false);}
 }
 return <Dialog.Root open={open} onOpenChange={setOpen}>
  <Dialog.Trigger className="circle-button" title="Поделиться тайтлом" aria-label="Поделиться тайтлом"><Share2 size={17}/></Dialog.Trigger>
  <Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog">
   <Dialog.Close className="icon-button dialog-close" aria-label="Закрыть"><X size={18}/></Dialog.Close>
   <Dialog.Title>Поделиться тайтлом</Dialog.Title>
   <Dialog.Description>{title.title||title.name}{dub?' · '+dub:''}</Dialog.Description>
   {kind==='manga'&&!link&&<label className="reader-checkbox"><input type="checkbox" checked={translate} onChange={e=>setTranslate(e.target.checked)}/>Открывать с переводом на русский</label>}
   <p className="fine">Получатель ссылки сможет открыть выбранный перевод и серии или главы этого тайтла. Доступ действует до закрытия ссылки владельцем.</p>
   {link?<><input className="field-input" aria-label="Ссылка на тайтл" readOnly value={link} onFocus={e=>e.target.select()}/><div className="form-actions"><button className="btn btn-primary" onClick={copy}>{copied?<Check size={16}/>:<Copy size={16}/>}Скопировать</button><button className="text-link" disabled={busy} onClick={revoke}>Закрыть доступ по ссылке</button></div></>:<button className="btn btn-primary" disabled={busy||service.status!=='connected'} onClick={create}>{busy?'Создаём…':'Создать ссылку'}</button>}
   {error&&<p className="inline-error" role="alert">{error}</p>}
  </Dialog.Content></Dialog.Portal>
 </Dialog.Root>;
}
