// Scene search through trace.moe: a frame goes straight from this browser to
// api.trace.moe (each viewer spends their own free quota). Nothing is stored on
// our server. The answer is an AniList/MAL work, an episode and the exact second.
const API='https://api.trace.moe/search?anilistInfo&cutBorders';
const JUMP='mv_scene_jump_v1';
export const CONFIDENT=.88;

export function sceneEpisode(value){
 if(Array.isArray(value))value=value[0];
 const number=typeof value==='number'?value:parseFloat(String(value??'').replace(',','.'));
 return Number.isFinite(number)&&number>0?Math.floor(number):1;
}
export function clock(seconds){
 const v=Math.max(0,Math.floor(Number(seconds)||0)),h=Math.floor(v/3600),m=Math.floor(v%3600/60),s=String(v%60).padStart(2,'0');
 return h?h+':'+String(m).padStart(2,'0')+':'+s:m+':'+s;
}
// trace.moe repeats the same scene from several encodes; keep one row per work+episode.
export function sceneMatches(result=[]){
 const rows=new Map();
 for(const row of result){
  const anilist=row?.anilist;if(!anilist||typeof anilist!=='object')continue;
  const episode=sceneEpisode(row.episode),key=anilist.id+':'+episode;
  if(rows.has(key)&&rows.get(key).similarity>=row.similarity)continue;
  rows.set(key,{key,anilistId:anilist.id,mal:anilist.idMal?String(anilist.idMal):'',title:anilist.title?.english||anilist.title?.romaji||anilist.title?.native||'Аниме',original:anilist.title?.native||'',adult:!!anilist.isAdult,
   episode,time:Number(row.at??row.from)||0,from:Number(row.from)||0,to:Number(row.to)||0,similarity:Number(row.similarity)||0,
   video:/^https:\/\/api\.trace\.moe\/video\//.test(row.video||'')?row.video:'',image:/^https:\/\/api\.trace\.moe\/image\//.test(row.image||'')?row.image:''});
 }
 return [...rows.values()].sort((a,b)=>b.similarity-a.similarity).slice(0,5);
}
// Large screenshots are scaled down before upload: faster and well under the 25 MB limit.
export async function prepareFrame(file){
 if(!file||!/^image\//.test(file.type))throw Error('Это не картинка. Перетащи скриншот кадра.');
 if(file.size<=1.5*1024*1024)return file;
 const bitmap=await createImageBitmap(file),scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height));
 const canvas=document.createElement('canvas');canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
 canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close?.();
 return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(Error('Не удалось подготовить кадр.')),'image/jpeg',.9));
}
function failure(status,detail){
 if(status===402||status===429)return 'Лимит бесплатных поисков trace.moe на этот месяц исчерпан или сервис занят. Попробуй позже.';
 if(status===400)return 'trace.moe не смог прочитать картинку. Нужен обычный кадр без рамок и надписей.';
 return detail||'trace.moe сейчас не отвечает. Повтори немного позже.';
}
export async function searchScene(source,{signal,fetcher=fetch}={}){
 const options={method:'POST',signal:AbortSignal.any([signal,AbortSignal.timeout(45000)].filter(Boolean))};
 let url=API;
 if(typeof source==='string'){if(!/^https:\/\//.test(source))throw Error('Нужна картинка или ссылка https.');url+='&url='+encodeURIComponent(source);options.method='GET';}
 else{const frame=await prepareFrame(source);options.body=frame;options.headers={'Content-Type':frame.type||'image/jpeg'};}
 let response;try{response=await fetcher(url,options);}catch(e){if(signal?.aborted)throw e;throw Error('trace.moe недоступен. Проверь соединение.');}
 const data=await response.json().catch(()=>({}));
 if(!response.ok||data.error)throw Error(failure(response.status,typeof data.error==='string'&&data.error?'trace.moe: '+data.error:''));
 return {matches:sceneMatches(data.result),remaining:Number(response.headers.get('x-ratelimit-remaining'))};
}
export async function russianTitles(ids,signal){
 const clean=[...new Set(ids.filter(id=>/^\d+$/.test(id)))];if(!clean.length)return {};
 try{const r=await fetch('https://shikimori.io/api/animes?'+new URLSearchParams({ids:clean.join(','),limit:'50'}),{signal});if(!r.ok)return {};const rows=await r.json();return Object.fromEntries(rows.filter(r=>r?.id).map(r=>[String(r.id),{title:r.russian||r.name,cover:r.image?.original?'https://shikimori.io'+r.image.original:''}]));}catch{return {};}
}
// Hand-off to the title page: it opens this episode and seeks to the second.
export function requestSceneJump(match,storage=sessionStorage){try{storage.setItem(JUMP,JSON.stringify({mal:match.mal,episode:match.episode,time:Math.max(0,match.time-2),at:Date.now()}));}catch{}}
export function readSceneJump(mal,storage=sessionStorage){
 try{const value=JSON.parse(storage.getItem(JUMP)||'null');if(!value||String(value.mal)!==String(mal)||Date.now()-value.at>10*60*1000)return null;return value;}catch{return null;}
}
export function consumeSceneJump(storage=sessionStorage){try{storage.removeItem(JUMP);}catch{}}
