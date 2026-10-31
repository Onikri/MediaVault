// Public, free metadata only. Video extraction does not use these APIs.
import {creditsFromRoles} from './credits.js';
import {crossMediaFromLinks,highResolutionArtwork} from './cross-media.js';
const ORIGIN='https://shikimori.io';
const pending=new Map();
let lastRequest=0;
export const hasRussian=value=>/[а-яё]/i.test(String(value||''));
export function plainText(value){
  return String(value||'').replace(/<br\s*\/?\s*>/gi,'\n').replace(/<\/(?:p|div|li|h[1-6])>/gi,'\n\n').replace(/<[^>]*>/g,'').replace(/\[(?:\/?[a-z_]+)(?:[^\]]*)\]/gi,'').replace(/&nbsp;/g,' ').replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/\n{3,}/g,'\n\n').trim();
}
export const russianText=value=>{const text=plainText(value),letters=(text.match(/\p{L}/gu)||[]).length,cyrillic=(text.match(/[а-яё]/gi)||[]).length;return cyrillic&&cyrillic/Math.max(1,letters)>=.25?text:'';};
export function imageURL(value){
  if(!value||typeof value!=='string'||/(?:\/|_)(?:404|missing|no[_-]?image)(?:[.\/_-]|$)/i.test(value))return '';
  try{const url=new URL(value,ORIGIN);return url.protocol==='https:'&&!url.username&&!url.password?url.href:'';}catch{return '';}
}
export const translated={tv:'Аниме',movie:'Фильм',ova:'OVA',ona:'ONA',special:'Спецвыпуск',music:'Музыкальное видео',manga:'Манга',novel:'Ранобэ',light_novel:'Ранобэ',one_shot:'Ваншот',manhwa:'Манхва',manhua:'Маньхуа',released:'Завершён',ongoing:'Выходит',anons:'Анонсирован',manga_source:'Манга',original:'Оригинальное произведение',light_novel_source:'Ранобэ',novel_source:'Роман',game:'Игра',visual_novel:'Визуальная новелла',webtoon:'Вебтун',web_manga:'Веб-манга',four_koma_manga:'Ёнкома',book:'Книга',other:'Другое'};
export const translate=(value,fallback='Не указано')=>translated[String(value||'').toLowerCase()]||(hasRussian(value)?String(value):fallback);
export function importedProfile(value){
  if(!value||!Object.keys(value).length)return null;
  return {version:4,partial:true,language:'ru',title:russianText(value.titles?.ru)||russianText(value.title),sourceId:value.ids?.mal||'',
    description:russianText(value.description),cover:imageURL(value.cover),background:imageURL(value.background),
    genres:(value.genres||[]).filter(hasRussian),themes:(value.tags||[]).filter(hasRussian),format:translate(value.format),status:translate(value.status),
    year:value.year,startDate:value.startDate,endDate:value.endDate,episodes:value.episodes,chapters:value.chapters,volumes:value.volumes,rating:value.age?value.age+'+':'',characters:[],related:[],screenshots:[]};
}
const themeNames=new Set(['Меха','Психологическое','Школа','Военное','Самураи','Пародия','Полиция','Космос','Исекай','Путешествия во времени','Вампиры','Выживание']);
const nameOf=(value,fallback)=>russianText(value?.russian)||fallback;
const resource=kind=>['manga','ranobe','novel'].includes(kind)?'mangas':'animes';
export function normalizeProfile(data,{roles=[],related=[],screenshots=[]}={}){
  const id=String(data.id),kind=['manga','novel','light_novel','manhwa','manhua','one_shot','web_manga','webtoon'].includes(data.kind)?'manga':'anime';
  const chars=roles.filter(r=>r.character).sort((a,b)=>Number(b.roles?.includes('Main'))-Number(a.roles?.includes('Main'))).slice(0,18);
  const cover=imageURL(data.image?.original||data.image?.preview||'');
  return {version:4,language:'ru',source:'shikimori',sourceId:id,sourceURL:ORIGIN+(data.url||'/'+resource(kind)+'/'+id),kind,
    title:nameOf(data,'Название уточняется'),aliases:[data.name,...(data.english||[]),...(data.japanese||[]),...(data.synonyms||[])].filter(Boolean),
    description:russianText(data.description_html||data.description),cover,
    background:imageURL(screenshots[0]?.original||data.screenshots?.[0]?.original||''),
    screenshots:(screenshots.length?screenshots:data.screenshots||[]).slice(0,10).map(s=>imageURL(s.original||s.preview)).filter(Boolean),
    format:translate(data.kind),status:translate(data.status),year:Number(String(data.aired_on||'').slice(0,4))||null,
    startDate:data.aired_on||'',endDate:data.released_on||'',episodes:data.episodes||null,episodesAired:data.episodes_aired||null,
    chapters:data.chapters||null,volumes:data.volumes||null,duration:data.duration||null,
    score:Number(data.score)||null,ratingCode:{g:'G',pg:'PG',pg_13:'PG-13',r:'R-17',r_plus:'R+',rx:'Rx'}[data.rating]||'',rating:{g:'0+',pg:'6+',pg_13:'13+',r:'17+',r_plus:'18+',rx:'18+'}[data.rating]||'',
    origin:({manga:'Манга',light_novel:'Ранобэ',novel:'Роман',original:'Оригинальное произведение',game:'Игра',web_novel:'Веб-роман'}[data.source]||translate(data.source)),genres:(data.genres||[]).map(g=>nameOf(g,'')).filter(Boolean),themes:(data.genres||[]).filter(g=>/theme/i.test(g.entry_type||g.kind||'')||themeNames.has(g.russian)).map(g=>nameOf(g,'')).filter(Boolean),
    studioRefs:(data.studios||[]).map(s=>({id:String(s.id),name:s.name})),genreRefs:(data.genres||[]).map(g=>({id:String(g.id),name:g.russian||g.name})),statusCode:data.status,studios:(data.studios||[]).map(s=>s.name).filter(Boolean),staff:creditsFromRoles(roles),trailers:(data.videos||[]).filter(v=>v.kind==='pv'||v.kind==='character_trailer').map(v=>({id:String(v.id),title:russianText(v.name)||'Проморолик',url:imageURL((v.url||v.player_url||'').replace(/^http:/,'https:')),image:imageURL((v.image_url||'').replace(/^http:/,'https:')),hosting:v.hosting})),directors:roles.filter(r=>r.person&&r.roles?.includes('Director')).map(r=>nameOf(r.person,'Имя уточняется')),
    characters:chars.map(r=>({id:String(r.character.id),name:nameOf(r.character,'Персонаж №'+r.character.id),role:(r.roles_russian||[]).filter(hasRussian).join(', ')||(r.roles?.includes('Main')?'Главный герой':'Персонаж'),image:imageURL(r.character.image?.original||r.character.image?.preview||''),description:''})),
    related:related.map(r=>{const t=r.anime||r.manga;if(!t)return null;return {id:String(t.id),kind:r.manga?['novel','light_novel'].includes(t.kind)?'ranobe':'manga':'anime',title:nameOf(t,'Связанное произведение'),relation:russianText(r.relation_russian)||'Связано',cover:imageURL(t.image?.original||t.image?.preview||''),year:Number(String(t.aired_on||'').slice(0,4))||null,format:translate(t.kind)};}).filter(Boolean).slice(0,24),
    fetchedAt:new Date().toISOString()};
}
async function request(path,{signal,server}={}){
  signal?.throwIfAborted();
  const key=path;
  if(!pending.has(key)){
    const work=(async()=>{
      const match=path.match(/^(animes|mangas|characters|people)\/(\d+)(?:\/(roles|related|screenshots|external_links))?$/),list=!match||!!match[3];
      const valid=value=>list?Array.isArray(value):value&&String(value.id)===match[2];
      const targets=[];
      if(server&&match)targets.push(server+'/metadata/shikimori?'+new URLSearchParams({identity:match[2],kind:match[1]==='people'?'person':match[1]==='characters'?'character':match[1]==='mangas'?'manga':'anime',...(match[3]?{part:match[3]}:{})}));
      targets.push(ORIGIN+'/api/'+path);
      for(const target of targets){
        try{
          if(target.startsWith(ORIGIN)){const start=Math.max(Date.now(),lastRequest+400);lastRequest=start;const delay=start-Date.now();if(delay)await new Promise(r=>setTimeout(r,delay));}
          const response=await fetch(target,{signal:AbortSignal.timeout(7500),headers:{Accept:'application/json'}});
          if(!response.ok)throw Error();const value=await response.json();if(!valid(value))throw Error();return value;
        }catch{}
      }
      throw Error('Шикимори сейчас недоступен. Можно повторить синхронизацию; сохранённые сведения остаются в Drive.');
    })();
    pending.set(key,work);work.catch(()=>pending.delete(key));
  }
  const value=await pending.get(key);signal?.throwIfAborted();return value;
}
export async function searchRussianTitles(name,kind='anime',options={}){
  const result=await request(resource(kind)+'?'+new URLSearchParams({search:name,limit:'8',order:'popularity'}),options);
  return result.map(data=>({...normalizeProfile(data),kind}));
}
export async function loadTitleProfile(id,kind='anime',options={}){
  if(!/^\d{1,12}$/.test(String(id)))throw Error('Укажи тайтл из каталога Шикимори.');
  kind=['manga','ranobe','novel'].includes(kind)?kind:'anime';const path=resource(kind)+'/'+id;
  if(options.refresh)for(const key of pending.keys())if(key===path||key.startsWith(path+'/'))pending.delete(key);
  const data=await request(path,options);
  const names=['roles','related',...(kind==='anime'?['screenshots']:[])];
  const extra=await Promise.allSettled(names.map(part=>request(path+'/'+part,options)));
  const values=extra.map(r=>r.status==='fulfilled'?r.value:[]);
  const profile=normalizeProfile(data,{roles:values[0],related:values[1],screenshots:values[2]});
  const enrichment=await Promise.allSettled([highResolutionArtwork(id,kind),request(path+'/external_links',options).then(crossMediaFromLinks)]);
  options.signal?.throwIfAborted();
  const art=enrichment[0].status==='fulfilled'?enrichment[0].value:null,cross=enrichment[1].status==='fulfilled'?enrichment[1].value:[];
  if(art?.background){profile.backgrounds=[imageURL(art.background)].filter(Boolean);profile.artworkSources=[{provider:'anilist',url:art.sourceURL}];}
  if(art?.cover)profile.cover=imageURL(art.cover);
  for(const value of cross)if(!profile.related.some(item=>item.kind===value.kind&&(String(item.id)===String(value.ids?.mal||'')||item.title===value.title)))profile.related.push(value);
  if(options.server){
    const ids=[id,...profile.related.filter(r=>r.kind===kind).map(r=>r.id)].filter(v=>/^\d+$/.test(v));
    try{
      const response=await fetch(options.server+'/metadata/posters?'+new URLSearchParams({ids:[...new Set(ids)].join(','),kind}),{signal:options.signal||AbortSignal.timeout(10000)});
      if(response.ok){const posters=await response.json();if(imageURL(posters[id]?.cover))profile.cover=imageURL(posters[id].cover);
        profile.related=profile.related.map(value=>({...value,...(posters[value.id]?{cover:imageURL(posters[value.id].cover),title:russianText(posters[value.id].title)||value.title}:{})}));}
    }catch(cause){options.signal?.throwIfAborted();}
  }
  profile.related=[...new Map(profile.related.map(r=>[r.kind+':'+(r.ids?.mal||r.id),r])).values()];
  return {...profile,partial:extra.some(r=>r.status==='rejected')||!profile.description,missingParts:names.filter((_,i)=>extra[i].status==='rejected'),retryAfter:Date.now()+60000};
}
export async function loadCharacter(id,options={}){
  if(!/^\d{1,12}$/.test(String(id)))throw Error('Некорректный персонаж.');
  const data=await request('characters/'+id,options);
  return {id:String(data.id),voiceActors:(data.seyu||[]).filter(v=>russianText(v.russian)).map(v=>({id:String(v.id),name:russianText(v.russian),role:'Сэйю',image:imageURL(v.image?.original||'')})),name:nameOf(data,'Персонаж №'+id),description:russianText(data.description_html||data.description),image:imageURL(data.image?.original||''),actors:(data.seyu||[]).map(value=>nameOf(value,'')).filter(Boolean)};
}
export function profileArtwork(profile){
  return [...new Set([profile.cover,profile.background,...(profile.backgrounds||[]),...(profile.screenshots||[]),...(profile.characters||[]).map(c=>c.image),...(profile.related||[]).map(r=>r.cover),...(profile.staff||[]).map(r=>r.image),...(profile.characters||[]).flatMap(c=>(c.voiceActors||[]).map(a=>a.image)),...(profile.trailers||[]).map(t=>t.image)])].filter(Boolean);
}

export async function loadPerson(id,options={}){
 if(!/^\d{1,12}$/.test(String(id)))throw Error('Некорректный участник группы.');
 const data=await request('people/'+id,options);return {id:String(data.id),name:russianText(data.russian)||'Участник съёмочной группы',description:russianText(data.description_html||data.description),image:imageURL(data.image?.original),website:imageURL(data.website),birthday:data.birthday||null};
}
