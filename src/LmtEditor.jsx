// SPDX-License-Identifier: AGPL-3.0-or-later
import {useEffect,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {processOnBackend} from './reader-processing.js';

export default function LmtEditor({blob,config,result,service,onApply,onClose}){
 const [element,setElement]=useState(null),[loaded,setLoaded]=useState(false),[error,setError]=useState('');
 useEffect(()=>{
  if(!element||!loaded)return;
  const channel=new MessageChannel(),controllers=new Set();let closed=false;
  const port=channel.port1;
  const receive=async({data})=>{
   if(closed)return;
   if(data.type==='ready'){
    const bytes=await blob.arrayBuffer();if(closed)return;
    port.postMessage({type:'init',bytes,config:{...config,engine:config.engine==='lmt'?'lmt':'backend'},result:structuredClone(result)},[bytes]);
   }else if(data.type==='stage'){
    const abort=new AbortController();controllers.add(abort);
    try{
     const options={translate:true,upscale:false,operation:data.operation,boxes:data.boxes||null,
      gateForce:!!data.gateForce,language:config.language||'English',targetLanguage:config.targetLanguage||'Russian',
      ocr:config.ocr||'paddle',detector:config.detector||'comic-bubble',inpaint:config.inpaint||'fast',
      allowDownloads:!!config.allowDownloads,contextKey:config.contextKey||'default'};
     const value=await processOnBackend(new Blob([data.bytes]),options,service,abort.signal,status=>{if(!closed)port.postMessage({type:'progress',status});});
     if(!closed)port.postMessage({type:'stage-result',id:data.id,result:value});
    }catch(e){if(!closed)port.postMessage({type:'stage-result',id:data.id,error:e.message});}
    finally{controllers.delete(abort);}
   }else if(data.type==='apply'){onApply(data.result);onClose();}
   else if(data.type==='close')onClose();
  };
  port.onmessage=event=>{void receive(event).catch(e=>!closed&&setError(e.message));};port.start();
  element.contentWindow.postMessage({type:'mv-lmt-editor-connect'},location.origin,[channel.port2]);
  return()=>{closed=true;for(const controller of controllers)controller.abort();port.close();};
 },[element,loaded]);
 return <Dialog.Root open onOpenChange={value=>!value&&onClose()}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="lmt-editor-dialog" onKeyDown={e=>e.stopPropagation()}><Dialog.Title className="sr-only">Редактор Libre Manga Translator</Dialog.Title><Dialog.Description className="sr-only">Уточнение областей, переводов и оформления страницы.</Dialog.Description>{error&&<p role="alert">{error}</p>}<iframe ref={setElement} onLoad={()=>setLoaded(true)} title="Редактор Libre Manga Translator" src={new URL('lmt/editor.html',new URL(import.meta.env.BASE_URL,location.href)).href}/><Dialog.Close className="lmt-editor-close">Закрыть</Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>;
}
