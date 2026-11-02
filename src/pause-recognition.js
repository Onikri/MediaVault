import {recognizeCharacters} from './character-recognition.js';
import {cachedCharacterRoster,localizeCharacters} from './pause-character-context.js';
import {detectPauseCharacters} from './pause-character-gemini.js';
function hintsWithin(promise,ms,signal){return new Promise((resolve,reject)=>{const finish=(value,error)=>{clearTimeout(timer);signal?.removeEventListener('abort',cancel);error?reject(error):resolve(value);},cancel=()=>finish(null,signal.reason),timer=setTimeout(()=>finish(null),ms);signal?.addEventListener('abort',cancel,{once:true});if(signal?.aborted)cancel();promise.then(v=>finish(v),()=>finish(null));});}
export function mergeFrameCharacters(primary,hints){
 const result=primary.map(c=>({...c}));
 for(const hint of hints){const [x1,y1,x2,y2]=hint.box,x=(x1+x2)/2,y=(y1+y2)/2,hit=result.find(c=>{const b=c.bodyBox||c.box;return x>=b[0]&&x<=b[2]&&y>=b[1]&&y<=b[3];});
  if(hit){hit.candidates=hint.candidates;if(!hit.nameRu&&hint.nameRu&&!hint.uncertain){hit.nameRu=hint.nameRu;hit.uncertain=false;hit.verification='catalog';}if(hint.box[0]>=hit.bodyBox?.[0]&&hint.box[1]>=hit.bodyBox?.[1]&&hint.box[2]<=hit.bodyBox?.[2]&&hint.box[3]<=hit.bodyBox?.[3])hit.box=hint.box;}
  else if(result.length<8)result.push(hint);
 }return result;
}
export async function recognizePauseFrame(image,context,{signal,onPartial=()=>{},trace=recognizeCharacters,detect=detectPauseCharacters,hintMs=350,...options}={}){
 const traceAbort=new AbortController(),bounded=signal?AbortSignal.any([signal,traceAbort.signal]):traceAbort.signal,roster=cachedCharacterRoster(context);let hints=[];
 const blob=await new Promise(resolve=>image.toBlob(resolve,'image/jpeg',.82));signal?.throwIfAborted();if(!blob)throw Error('Не удалось прочитать стоп-кадр.');
 const tracing=trace(blob,{signal:bounded}).then(values=>{if(bounded.aborted)return [];hints=localizeCharacters(values,roster);onPartial(hints);return hints;}).catch(()=>[]);
 try{
  await hintsWithin(tracing,hintMs,signal);signal?.throwIfAborted();
  try{const values=await detect(image,hints,{...context,roster},{...options,signal});signal?.throwIfAborted();return {values:mergeFrameCharacters(values,hints),complete:true};}
  catch(error){signal?.throwIfAborted();await tracing;signal?.throwIfAborted();if(hints.length)return {values:hints,complete:false,message:error.name==='TimeoutError'?'Gemini не ответил вовремя. Показан результат AnimeTrace.':error.message};throw error;}
 }finally{traceAbort.abort();}
}
