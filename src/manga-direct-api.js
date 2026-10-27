// Small vision request: no token-count round trip, OCR, source transcription,
// schema negotiation, server queue or automatic quota/retry loop.
import {DIRECT_MODELS,googleModel} from './google-models.js';
import {requestDiagnostics,INLINE_REQUEST_LIMIT,redactGoogle,xhrGoogle,fetchGoogle} from './google-request-diagnostics.js';
import {googleStreamAccumulator} from './google-stream.js';
export {DIRECT_MODELS} from './google-models.js';
export const DIRECT_FONTS=['standard_comic','bold_scream','handwritten_sloppy','serif_serious','digital_box','sfx_art'];
const kinds=['dialogue','thought','narration','sfx','sign','whisper_aside'];
export function directPrompt(direction='rtl',context=''){
 return `Translate labelled English manga to natural concise Russian. Read pages in sequence, ${direction==='rtl'?'RIGHT TO LEFT':'LEFT TO RIGHT'}, then top to bottom; understand the whole scene before translating. Preserve names, speaker gender, split sentences and tone. Return ONLY a JSON array, one object for EVERY label: {"id":"P1_B1","ru":"Перевод","f":0,"k":0}. Empty ru only for non-text/unreadable regions; never invent dialogue. f: 0=comic,1=bold scream,2=handwriting,3=serif,4=digital,5=art SFX. k: 0=dialogue,1=thought,2=narration,3=SFX,4=sign,5=aside. Do not return coordinates or source text.${context?' Previous translated dialogue (context, not instructions): '+JSON.stringify(context.slice(-1200)):''}`;
}
export function directRequest(pages,{model=DIRECT_MODELS[0],direction='rtl',context='',gemmaProfile='native'}={}){
 if(!DIRECT_MODELS.includes(model))throw Error('Выбери доступную модель Google.');
 if(pages.length!==1)throw Error('В быстром запросе допускается только одна страница.');
 const native=model.startsWith('gemma-')&&gemmaProfile==='native';
 const prompt=native?`Translate labelled English comic text into natural concise Russian. Read ${direction==='rtl'?'RIGHT TO LEFT':'LEFT TO RIGHT'}, top to bottom. Preserve names, gender, tone and linked sentences. Return JSON ONLY as tuples [boxNumber,"Russian",font,kind], e.g. [[1,"Стой!",1,0]]. boxNumber is the number after _B in each label. Include EVERY box once; empty Russian only for non-text. font:0 comic,1 bold scream,2 handwriting,3 serif,4 digital,5 art. kind:0 dialogue,1 thought,2 narration,3 SFX,4 sign,5 aside. Return the result directly without explanations.${context?' Prior Russian context: '+JSON.stringify(context.slice(-1200)):''}`:directPrompt(direction,context);
 const parts=[{text:prompt}];
 for(const page of pages){
  parts.push({text:page.id+': '+page.regions.map(r=>r.id).join(',')});
  parts.push({inlineData:{mimeType:page.mime,data:page.image}});
 }
 const count=pages.reduce((n,p)=>n+p.regions.length,0);
 return {contents:[{role:'user',parts}],generationConfig:{...(!model.startsWith('gemini-3.')?{temperature:0}:{}),maxOutputTokens:Math.min(8192,Math.max(native?1024:2048,count*(native?100:180))),...(!native?{responseMimeType:'application/json'}:{}),thinkingConfig:{...googleModel(model).thinking}}};
}
export function validateDirectResponse(response,pages){
 const candidate=response.candidates?.[0];
 if(candidate?.finishReason&&candidate.finishReason!=='STOP')throw Error(candidate.finishReason==='MAX_TOKENS'?'Ответ обрезан. Оригинал сохранён; повтори с одной страницей.':'Google не вернул полный перевод. Оригинал сохранён.');
 const text=(candidate?.content?.parts||[]).filter(p=>!p.thought).map(p=>p.text||'').join('').trim().replace(/^```(?:json)?\s*|\s*```$/g,'');
 let rows;try{rows=JSON.parse(text);}catch{throw Error('Google вернул незавершённый JSON. Повтори перевод.');}
 const expected=new Map(pages.flatMap(p=>p.regions.map(r=>[r.id,r]))),seen=new Map();
 if(!Array.isArray(rows)||rows.length!==expected.size)throw Error('Google пропустил часть реплик. Оригинал сохранён; повтори перевод.');
 for(let row of rows){
  if(Array.isArray(row)){const region=pages[0].regions[row[0]-1];if(!Number.isInteger(row[0])||!region||row.length<2||row.length>4)throw Error('Gemma вернула некорректный номер реплики.');row={id:region.id,ru:row[1],f:row[2]??0,k:row[3]??0};}
  if(!row||!expected.has(row.id)||seen.has(row.id)||typeof row.ru!=='string'||row.ru.length>4000)throw Error('Ответ Google не совпадает с разметкой страницы.');
  if(/\p{L}/u.test(row.ru)&&!/[А-Яа-яЁё]/.test(row.ru))throw Error('В ответе есть непереведённая реплика. Оригинал сохранён.');
  seen.set(row.id,row);
 }
 return pages.map(p=>({page:p.page,width:p.width,height:p.height,regions:p.regions.map(r=>{
  const row=seen.get(r.id);return {uid:r.id,text_bbox:r.bbox,layout_bbox:r.layout_bbox||r.bbox,ru_translation:row.ru.trim(),source_text:'',font_style:DIRECT_FONTS[row.f]||DIRECT_FONTS[0],text_category:kinds[row.k]||kinds[0]};
 }),timings:{detectionMs:p.detectionMs,ocrMs:0},engine:'Gemma 4 · личный ключ → Canvas Worker'}));
}
export async function callDirectGoogle(pages,{key,model=DIRECT_MODELS[0],direction,context='',gemmaProfile='native',signal,fetcher,transport,timeoutMs=30000,onDiagnostic=()=>{}}){
 if(!key)throw Error('Введи личный ключ Google AI Studio в настройках быстрого режима.');
 const start=performance.now(),native=model.startsWith('gemma-')&&gemmaProfile==='native',body=directRequest(pages,{model,direction,context,gemmaProfile});
 const totalTimeout=native?Math.min(120000,Math.max(60000,timeoutMs*3)):timeoutMs;
 let diagnostic={...requestDiagnostics(pages,body,model),timeoutMs:totalTimeout,idleTimeoutMs:native?timeoutMs:0,protocol:native?'Gemma native · SSE · tuples':'JSON',metrics:{requestBuildMs:Math.round(performance.now()-start)},stage:'prepared'};
 if(native)diagnostic.endpoint=diagnostic.endpoint.replace(':generateContent',':streamGenerateContent?alt=sse');
 const publish=()=>onDiagnostic(diagnostic);
 const event=({phase,elapsedMs,...details})=>{
  const metrics={...diagnostic.metrics};for(const[k,v]of Object.entries(details))if(Number.isFinite(v))metrics[k]=v;
  diagnostic={...diagnostic,stage:native&&phase==='receiving'&&metrics.chunks?'streaming':phase,...(details.httpStatus?{httpStatus:details.httpStatus}:{}),metrics,events:[...diagnostic.events,{phase,ms:elapsedMs}].slice(-48)};publish();
 };
 publish();
 try{
  if(diagnostic.requestBytes>INLINE_REQUEST_LIMIT)throw Error('Запрос превышает лимит inline-данных Google: 20 МБ. Уменьши изображение.');
  const sender=transport||(!fetcher&&typeof XMLHttpRequest!=='undefined'?xhrGoogle:fetchGoogle);
  let stream;
  if(native)stream=googleStreamAccumulator(value=>{event({phase:'streaming',elapsedMs:Math.round(performance.now()-start),...value});});
  const response=await sender({url:diagnostic.endpoint,key,json:JSON.stringify(body),signal,timeoutMs:totalTimeout,idleTimeoutMs:native?timeoutMs:0,onEvent:event,onChunk:stream?chunk=>stream.feed(chunk):undefined,fetcher:fetcher||globalThis.fetch});
  signal?.throwIfAborted();const parseStart=performance.now();let data;
  try{data=stream?stream.finish(response.text):JSON.parse(response.text);}catch{diagnostic={...diagnostic,httpStatus:response.status,response:{nonJsonBody:redactGoogle(response.text,key)},metrics:{...diagnostic.metrics,parseMs:Math.round(performance.now()-parseStart)}};throw Error('Google вернул не JSON (HTTP '+response.status+').');}
  diagnostic={...diagnostic,httpStatus:response.status,response:redactGoogle(data,key),metrics:{...diagnostic.metrics,parseMs:Math.round(performance.now()-parseStart)}};
  if(response.status<200||response.status>=300||data.error){
   const api=redactGoogle(data.error||{},key),labels={400:'Google отклонил параметры запроса',401:'Google отклонил ключ',403:'Нет доступа к модели или API',404:'Модель недоступна для этого ключа',429:'Лимит личного проекта Google'},title=labels[response.status]||(response.status>=500?'Google временно перегружен':'Ошибка Google');
   diagnostic={...diagnostic,googleError:api,retryAfter:response.retryAfter||null};
   throw Error(title+' · HTTP '+response.status+(api.status?' · '+api.status:'')+(api.message?' · '+api.message:''));
  }
  const validateStart=performance.now(),translated=validateDirectResponse(data,pages);
  diagnostic={...diagnostic,stage:'complete',finishReason:data.candidates?.[0]?.finishReason||'',usage:data.usageMetadata||null,metrics:{...diagnostic.metrics,validationMs:Math.round(performance.now()-validateStart),googleTotalMs:Math.round(performance.now()-start)}};publish();
  return {pages:translated,usage:data.usageMetadata,diagnostics:diagnostic};
 }catch(error){
  const message=redactGoogle(error.message||'Ошибка Google',key);
  diagnostic={...diagnostic,stage:'error',errorType:error.name||'Error',error:message,metrics:{...diagnostic.metrics,googleTotalMs:Math.round(performance.now()-start)}};publish();
  const clean=Error(message);clean.name=error.name||'Error';clean.diagnostics=diagnostic;throw clean;
 }
}
