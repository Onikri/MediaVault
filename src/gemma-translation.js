// Device detection/LaMa + authenticated backend Google jobs. No OCR or API key.
import {translateLmt} from './lmt-client.js';
const memory=new Map();
const sleep=(ms,signal)=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(signal.reason);},timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();});
export async function translateGemmaBatch(inputs,service,signal,status=()=>{}){
 if(service?.status!=='connected')throw Error('Подключи профиль владельца к ВМ для перевода через Google.');
 const prepared=[],results=Array(inputs.length),indices=[];
 for(const [i,input]of inputs.entries()){
  signal.throwIfAborted();status(i,'RT-DETR · подготавливаем страницу '+(i+1)+'/'+inputs.length);
  try{
   const page=await translateLmt(input.blob,{...input.config,mode:'gemma',operation:'gemma-prepare'},signal,text=>status(i,text));
   if(!page.regions.length){results[i]={renderedImage:await input.blob.arrayBuffer(),renderedMime:input.blob.type||'image/jpeg',regions:[],engine:'RT-DETR Comic v4',inputMode:'vision',message:'Текстовые области не найдены.',timings:{detectionMs:page.detectionMs,ocrMs:0},warnings:[]};continue;}
   prepared.push(page);indices.push(i);
  }catch(error){results[i]=error;}
 }
 if(!prepared.length)return results;
 const config=inputs[indices[0]].config,contextKey=config.contextKey||'chapter';
 const pages=prepared.map(({id,width,height,image,mime,regions})=>({id,width,height,image,mime,regions}));
 const {id}=await service.request('/reader/lmt/gemma/jobs',{method:'POST',body:{pages,model:config.directModel,language:config.language,context:memory.get(contextKey)||''},signal});
 let done=false;
 try{
  const until=Date.now()+15*60*1000;let result;
  while(Date.now()<until){
   signal.throwIfAborted();const task=await service.request('/reader/lmt/gemma/jobs/'+id,{signal});
   for(const i of indices)status(i,task.status||'Переводим пакет Google…');
   if(task.state==='done'){result=task.result;done=true;break;}
   if(['error','cancelled'].includes(task.state))throw Error(task.status||'Перевод Google остановлен.');
   await sleep(900,signal);
  }
  if(!result||!Array.isArray(result.pages)||result.pages.length!==prepared.length)throw Error('Сервер не вернул все страницы пакета. Оригиналы сохранены.');
  memory.set(contextKey,JSON.stringify(result.pages.flatMap(p=>p.regions.filter(r=>r.status==='translated').map(r=>({id:r.id,text:r.translation,gender:r.speaker_gender})))).slice(-3800));while(memory.size>8)memory.delete(memory.keys().next().value);
  for(const [n,page]of prepared.entries()){
   const i=indices[n],input=inputs[i],translation=result.pages.find(p=>p.id===page.id);
   try{
    if(!translation)throw Error('Ответ относится к другой странице.');
    const{image,mime,...geometry}=page;
    results[i]=await translateLmt(input.blob,{...input.config,mode:'gemma',operation:'gemma-render',prepared:geometry,translation,cloudMs:result.cloudMs,usage:result.usage},signal,text=>status(i,text));
   }catch(error){results[i]=error;}
  }
  return results;
 }finally{if(!done)service.request('/reader/lmt/gemma/jobs/'+id+'/cancel',{method:'POST'}).catch(()=>{});}
}
globalThis.addEventListener?.('mediavault-locked',()=>memory.clear());
