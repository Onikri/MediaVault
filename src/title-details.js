// Catalogue facts and reader availability are different: an ongoing title's
// planned total must never be presented as its number of published episodes.
const key=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]/gu,'');
const text=value=>typeof value==='string'&&value.trim()&&!['Название уточняется','Не указано','Без названия'].includes(value.trim());
export function titleNames(value={}){
 const seen=new Set();return [value.title,...Object.values(value.titles||{}),...(value.aliases||[])].filter(text).map(v=>v.trim()).filter(v=>{const k=key(v);if(!k||seen.has(k))return false;seen.add(k);return true;}).slice(0,30);
}
export function alternativeTitleNames(value,current=value?.title){return titleNames(value).filter(v=>key(v)!==key(current)).sort((a,b)=>Number(/[а-яё]/i.test(b))-Number(/[а-яё]/i.test(a)));}
export function mergeTitleIdentity(item,profile={}){
 const aliases=titleNames({...item,aliases:[...titleNames(profile),...(item.aliases||[])]});
 const russian=text(profile.title)&&/[а-яё]/i.test(profile.title)?profile.title:'';
 // The original catalogue IDs, kind and year remain the identity authority.
 return {...item,aliases,...(russian?{title:russian,titles:{...item.titles,ru:russian}}:{})};
}
export function profileCatalogFields(item={}){
 item=item||{};
 return {aliases:titleNames(item),titles:item.titles,episodes:item.episodes,episodesAired:item.episodesAired,chapters:item.chapters,volumes:item.volumes,startDate:item.startDate,endDate:item.endDate,duration:item.duration};
}
export function preserveCatalogFacts(item,profile={}){
 const original=profileCatalogFields(item),extra=profileCatalogFields(profile);
 return {...original,...Object.fromEntries(Object.entries(extra).filter(([,v])=>v!==undefined&&v!==null&&v!==''&&(!Array.isArray(v)||v.length)))};
}
const number=value=>value!==null&&value!==''&&value!==undefined&&Number.isFinite(Number(value))&&Number(value)>=0?Number(value):null;
export function mangaPublication(inspection){
 if(inspection?.readable!==true)return null;
 const chapters=new Map();
 for(const row of inspection.episodes||[]){const n=number(row.number);if(n!==null&&row.url)chapters.set((row.season||1)+':'+n,n);}
 if(!chapters.size)return null;
 return {count:chapters.size,latest:Math.max(...chapters.values()),language:inspection.language,providerName:inspection.providerName,truncated:!!inspection.truncated};
}
export function publicationFacts(profile={},kind='anime',now=Date.now()){
 const out=[],add=(label,value)=>{if(value!==null&&value!==undefined&&value!=='')out.push([label,String(value)]);};
 if(['manga','ranobe'].includes(kind)){
  add('Главы в каталоге',number(profile.chapters));add('Тома',number(profile.volumes));
  const source=profile.sourcePublication;
  if(source){const language={ru:'Русский',uk:'Украинский',en:'Английский',ja:'Японский',ko:'Корейский'}[source.language];
   add('Главы в источнике',(source.truncated?'не менее ':'')+source.count+(language?' · '+language:''));
   add('Последняя глава в источнике',source.latest);
  }
  return out;
 }
 const total=number(profile.episodes),ongoing=/ongoing|releasing|current|publishing|выходит/i.test(profile.status||'');
 const releases=(profile.releases||[]).filter(r=>!r.season||Number(r.season)===Number(profile.season||1)).filter(r=>r.date&&Date.parse(r.date)<=now&&number(r.episode)!==null);
 const released=number(profile.episodesAired),latest=releases.length?Math.max(...releases.map(r=>Number(r.episode))):null;
 const aired=released===null?latest:Math.max(released,latest??0);
 if(aired!==null){add('Выпущено серий',aired);if(aired>0)add('Последняя серия',Math.max(aired,latest??0));}
 if(total!==null)add(ongoing?'Серий запланировано':'Эпизоды',total);
 return out;
}
