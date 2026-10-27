export const INLINE_REQUEST_LIMIT=20_000_000;
export const byteLength=value=>new TextEncoder().encode(value).byteLength;
export const base64Bytes=value=>Math.floor(value.length*3/4)-(value.endsWith('==')?2:value.endsWith('=')?1:0);
export function requestDiagnostics(pages,body,model){
 const json=JSON.stringify(body),images=pages.map(p=>({page:p.page,id:p.id,width:p.width,height:p.height,sentWidth:p.sentWidth||Math.round(p.width*Math.min(1,1280/Math.max(p.width,p.height))),sentHeight:p.sentHeight||Math.round(p.height*Math.min(1,1280/Math.max(p.width,p.height))),mime:p.mime,bytes:base64Bytes(p.image),base64Chars:p.image.length,regions:p.regions.length}));
 return {version:2,model,inputMode:pages[0]?.inputMode||'annotated',detector:pages[0]?.detector||'local',modelInputLimit:googleModel(model)?.inputLimit||null,modelOutputLimit:googleModel(model)?.outputLimit||null,method:'POST',endpoint:'https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',requestBytes:byteLength(json),limitBytes:INLINE_REQUEST_LIMIT,pages:pages.length,boxes:images.reduce((n,i)=>n+i.regions,0),images,timeoutMs:30000,metrics:{},events:[],requestBody:body,
  requestPreview:{...body,contents:body.contents.map(c=>({...c,parts:c.parts.map(p=>p.inlineData?{inlineData:{mimeType:p.inlineData.mimeType,data:'[base64: '+p.inlineData.data.length+' символов; полное изображение — в скачиваемом JSON]'}}:p)}))},
  coordinates:pages.map(p=>({id:p.id,regions:p.regions.map(r=>({id:r.id,text_bbox:r.bbox}))}))};
}
export function redactGoogle(value,key=''){
 const visit=v=>{
  if(typeof v==='string')return (key?v.split(key).join('[ключ скрыт]'):v).replace(/(?:AIza|AQ\.)[A-Za-z0-9_.-]{15,}/g,'[ключ скрыт]').replace(/([?&](?:key|api_key)=)[^&\s]+/gi,'$1[скрыт]').slice(0,4000);
  if(Array.isArray(v))return v.slice(0,32).map(visit);
  if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).filter(([k])=>!/(?:api.?key|authorization|credential)/i.test(k)).slice(0,48).map(([k,x])=>[k,visit(x)]));
  return v;
 };return visit(value);
}
export function safeDiagnosticExport(d){
 if(!d)return null;
 const {requestBody,...safe}=d;return safe;
}

// XHR exposes request-upload events that Fetch does not expose. Upload elapsed
// includes connection/CORS; headers waiting includes Google and network time.
// Neither is advertised as pure wire time or model inference time.
export function xhrGoogle({url,key,json,signal,timeoutMs,onEvent,onChunk,idleTimeoutMs=0,xhrFactory=()=>new XMLHttpRequest()}){
 return new Promise((resolve,reject)=>{
  const xhr=xhrFactory(),start=performance.now();let uploadEnd=null,headersAt=null,firstAt=null,settled=false,cursor=0,idleTimer;
  const elapsed=()=>Math.round(performance.now()-start),emit=(phase,extra={})=>onEvent?.({phase,elapsedMs:elapsed(),...extra});
  const cleanup=()=>{clearTimeout(idleTimer);signal?.removeEventListener('abort',abort);},finish=(fn,value)=>{if(settled)return;settled=true;cleanup();fn(value);};
  const resetIdle=()=>{if(!idleTimeoutMs)return;clearTimeout(idleTimer);idleTimer=setTimeout(()=>{finish(reject,Object.assign(Error('Gemma не присылает данные '+idleTimeoutMs/1000+' с.'),{name:'TimeoutError'}));xhr.abort();},idleTimeoutMs);};
  const feed=()=>{if(!onChunk||settled)return true;const part=(xhr.responseText||'').slice(cursor);cursor=(xhr.responseText||'').length;if(!part)return true;try{onChunk(part);resetIdle();return true;}catch(error){finish(reject,error);xhr.abort();return false;}};
  const abort=()=>{xhr.abort();finish(reject,signal.reason||new DOMException('Отменено','AbortError'));};
  if(signal?.aborted){finish(reject,signal.reason);return;}
  signal?.addEventListener('abort',abort,{once:true});
  xhr.open('POST',url);xhr.timeout=timeoutMs;xhr.withCredentials=false;
  xhr.setRequestHeader('Content-Type','application/json');xhr.setRequestHeader('x-goog-api-key',key);
  xhr.upload.onprogress=e=>emit('uploading',{uploadLoaded:e.loaded,uploadTotal:e.lengthComputable?e.total:null});
  xhr.upload.onload=()=>{uploadEnd=elapsed();resetIdle();emit('waiting',{uploadMs:uploadEnd,uploadLoaded:byteLength(json),uploadTotal:byteLength(json)});};
  xhr.onreadystatechange=()=>{if(xhr.readyState>=2&&xhr.status>0&&headersAt===null){headersAt=elapsed();emit('headers',{httpStatus:xhr.status,headersMs:headersAt,waitAfterUploadMs:uploadEnd===null?null:Math.max(0,headersAt-uploadEnd)});}};
  xhr.onprogress=e=>{if(firstAt===null){firstAt=elapsed();emit('receiving',{firstByteMs:firstAt});}if(!feed())return;emit('receiving',{downloadLoaded:e.loaded,downloadTotal:e.lengthComputable?e.total:null});};
  xhr.onload=()=>{if(!feed())return;const end=elapsed();emit('received',{httpStatus:xhr.status,networkMs:end,downloadMs:headersAt===null?null:Math.max(0,end-headersAt),responseBytes:byteLength(xhr.responseText||'')});finish(resolve,{status:xhr.status,text:xhr.responseText||'',retryAfter:xhr.getResponseHeader('Retry-After')});};
  xhr.onerror=()=>finish(reject,Error('Сетевая ошибка или CORS: браузер не получил ответ Google.'));
  xhr.ontimeout=()=>finish(reject,Object.assign(Error('Google не ответил за '+timeoutMs/1000+' с.'),{name:'TimeoutError'}));
  xhr.onabort=()=>finish(reject,signal?.reason||new DOMException('Отменено','AbortError'));
  emit('sending',{sentAt:Date.now()});resetIdle();try{xhr.send(json);}catch(error){finish(reject,error);}
 });
}
export async function fetchGoogle({url,key,json,signal,timeoutMs,onEvent,fetcher}){
 const start=performance.now(),timeout=AbortSignal.timeout(timeoutMs),combined=signal?AbortSignal.any([signal,timeout]):timeout,elapsed=()=>Math.round(performance.now()-start);
 onEvent?.({phase:'sending',sentAt:Date.now(),elapsedMs:0,transport:'fetch'});
 try{
  const response=await fetcher(url,{method:'POST',headers:{'Content-Type':'application/json','x-goog-api-key':key},body:json,signal:combined,credentials:'omit',referrerPolicy:'no-referrer'}),headersMs=elapsed();
  onEvent?.({phase:'headers',httpStatus:response.status,headersMs,elapsedMs:headersMs});const text=await response.text();
  onEvent?.({phase:'received',httpStatus:response.status,networkMs:elapsed(),downloadMs:elapsed()-headersMs,responseBytes:byteLength(text),elapsedMs:elapsed()});
  return {status:response.status,text,retryAfter:response.headers?.get('Retry-After')};
 }catch(error){if(signal?.aborted)throw signal.reason;if(timeout.aborted)throw Object.assign(Error('Google не ответил за '+timeoutMs/1000+' с.'),{name:'TimeoutError'});throw error;}
}
import {googleModel} from './google-models.js';
