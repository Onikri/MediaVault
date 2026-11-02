// Official public API: https://www.animetrace.com/api-docs/
const BASE='https://api.animetrace.com/v1';let models;
export function parseCharacters(value){
 if(![0,200,17720].includes(value?.code)||!Array.isArray(value.data))throw Error('AnimeTrace не смог распознать кадр. Попробуй позже.');
 return value.data.slice(0,8).flatMap((v,i)=>{
  const b=v.box;if(!Array.isArray(b)||b.length!==4||!b.every(Number.isFinite)||b.some(n=>n<0||n>1)||b[2]<=b[0]||b[3]<=b[1])return [];
  const candidates=(Array.isArray(v.character)?v.character:[]).slice(0,8).flatMap(c=>typeof c.character==='string'&&c.character.trim()?[{name:c.character.trim().slice(0,120),work:typeof c.work==='string'?c.work.slice(0,160):''}]:[]);
  return candidates.length?[{id:String(i),box:b,candidates,uncertain:!!v.not_confident||new Set((v.character||[]).map(c=>c.character)).size>1}]:[];
 });
}
async function modelList(signal){
 if(models&&models.until>Date.now())return models.id;
 const response=await fetch(BASE+'/model/list',{signal,credentials:'omit',referrerPolicy:'no-referrer'});
 if(!response.ok)throw Error('Список моделей AnimeTrace временно недоступен.');
 const data=await response.json().catch(()=>{throw Error('AnimeTrace вернул неполный ответ.');}),enabled=(data.data||[]).filter(v=>v.enabled&&typeof v.id==='string');
 const selected=enabled.find(v=>v.default)||enabled[0];if(!selected)throw Error('AnimeTrace временно не принимает кадры.');
 models={id:selected.id,until:Date.now()+3600000};return selected.id;
}
export async function recognizeCharacters(blob,{signal}={}){
 const bounded=signal?AbortSignal.any([signal,AbortSignal.timeout(25000)]):AbortSignal.timeout(25000),model=await modelList(bounded),body=new FormData();
 body.append('model',model);body.append('is_multi','1');body.append('ai_detect','0');body.append('file',blob,'pause.jpg');
 const response=await fetch(BASE+'/search',{method:'POST',body,signal:bounded,credentials:'omit',referrerPolicy:'no-referrer'});
 if(!response.ok)throw Error(response.status===429?'AnimeTrace просит подождать. Повтори позже.':'Распознавание временно недоступно.');
 return parseCharacters(await response.json().catch(()=>{throw Error('AnimeTrace вернул неполный ответ.');}));
}
