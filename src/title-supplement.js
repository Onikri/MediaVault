import {localLabel} from './taxonomy.js';
import {russianText,translate} from './title-metadata.js';
import {youtubeTrailer} from './media-metadata.js';
export function jikanProfile(data,kind='anime'){
 if(!data?.mal_id)return {};
 const trailer=youtubeTrailer(data.trailer),cover=data.images?.webp?.large_image_url||data.images?.jpg?.large_image_url||'';
 return {sourceId:String(data.mal_id),source:'jikan',sourceURL:data.url,title:data.russian||data.title_english||data.title,cover,
  aliases:[data.title,data.title_english,data.title_japanese,...(data.titles||[]).map(x=>x.title)].filter(Boolean),description:russianText(data.synopsis),year:data.year||Number((data.aired?.from||data.published?.from||'').slice(0,4))||null,
  format:translate(data.type,kind==='anime'?'Аниме':'Манга'),status:({'Finished Airing':'Завершён','Currently Airing':'Выходит','Not yet aired':'Анонсирован','Finished':'Завершена','Publishing':'Выходит'})[data.status]||'',
  score:Number(data.score)||null,episodes:data.episodes||null,chapters:data.chapters||null,volumes:data.volumes||null,startDate:data.aired?.from||data.published?.from||'',endDate:data.aired?.to||data.published?.to||'',
  studios:(data.studios||[]).map(x=>x.name),studioRefs:(data.studios||[]).map(x=>({id:String(x.mal_id),name:x.name})),
  trailers:trailer?[{id:data.trailer.youtube_id,title:'Трейлер',url:trailer,image:data.trailer.images?.maximum_image_url||data.trailer.images?.large_image_url||'',hosting:'youtube'}]:[],
  characters:[],related:[],screenshots:[],genres:(data.genres||[]).map(x=>localLabel(x.name)),themes:(data.themes||[]).map(x=>localLabel(x.name))};
}
export function fillProfile(current={},extra={}){
 const out={...extra,...current};
 for(const [key,value] of Object.entries(extra))if(current[key]==null||current[key]===''||current[key]==='Не указано'||Array.isArray(current[key])&&!current[key].length)out[key]=value;
 if(current.title==='Название уточняется')out.title=extra.title||current.title;
 return out;
}
