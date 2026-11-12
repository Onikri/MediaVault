import {plural} from './title-context.js';

const CHAPTER=['глава','главы','глав'],VOLUME=['том','тома','томов'],EPISODE=['серия','серии','серий'],SEASON=['сезон','сезона','сезонов'],BOOK=['книга','книги','книг'],EDITION=['издание','издания','изданий'];
export const whole=value=>{const n=Math.round(Number(value));return Number.isFinite(n)&&n>0?n:0;};
export function runtime(minutes){const m=whole(minutes);if(!m)return '';const h=Math.floor(m/60);return h?h+' ч'+(m%60?' '+m%60+' мин':''):m+' мин';}
const ongoing=(status,code)=>code==='ongoing'||/выход|онгоинг|ongoing|running|публику/i.test(status||'');
const announced=(status,code)=>code==='anons'||/анонс/i.test(status||'');

// The size of a work and how much of it exists so far (released or translated).
export function passportVolume(kind,p,stats){
 const status=p.status,code=p.statusCode,live=ongoing(status,code),soon=announced(status,code);
 if(['manga','ranobe'].includes(kind)){
  const total=whole(p.chapters),volumes=whole(p.volumes),have=whole(stats?.chapters),haveVolumes=whole(stats?.volumes);
  const figures=total?[[total,CHAPTER],[volumes,VOLUME]]:have?[[have,CHAPTER],[haveVolumes,VOLUME]]:[[volumes,VOLUME]];
  const note=total&&have&&have<total?'Переведено '+have+' из '+total+(stats.sourceName?' · '+stats.sourceName:'')
   :!total&&have?(live?'Выходит · общее число глав ещё не объявлено':'Столько глав в источнике')+(stats.sourceName?' · '+stats.sourceName:'')
   :live&&total?'Выходит · по плану '+total+' '+plural(total,CHAPTER):soon?'Анонсировано':'';
  const units=volumes||haveVolumes||Math.ceil((total||have)/10);
  return {figures,joiner:', ',note,ruler:(total||have)?{units,filled:total&&have?have/total:live?.999:1,label:note||'Объём произведения'}:null};
 }
 if(['anime','tv'].includes(kind)){
  const episodes=whole(p.episodes),aired=whole(p.episodesAired)||whole(stats?.episodes),seasons=whole(p.seasons);
  const figures=kind==='tv'&&seasons?[[seasons,SEASON],[episodes,EPISODE]]:[[episodes||aired,EPISODE]];
  const per=runtime(p.duration);
  const note=[episodes&&aired&&aired<episodes?'Вышло '+aired+' из '+episodes:live&&!episodes&&aired?'Выходит · вышло '+aired:soon?'Анонсировано':'',per&&'Серия ≈ '+per].filter(Boolean).join(' · ');
  const units=kind==='tv'&&seasons>1?seasons:episodes||aired;
  return {figures,joiner:', ',note,ruler:units?{units,filled:episodes&&aired?aired/episodes:1,label:note||'Серии'}:null};
 }
 if(kind==='movie')return {figures:[],lead:runtime(p.duration),note:p.franchise?'Часть франшизы «'+p.franchise+'»':'',ruler:null};
 if(kind==='book'){
  const parts=whole(p.cycle?.parts);
  return {figures:p.cycle&&parts?[[parts,BOOK]]:[],lead:p.cycle&&!parts?'Цикл «'+p.cycle.title+'»':'',note:[p.cycle&&parts?'В цикле «'+p.cycle.title+'»':'',p.finished===false?'Не закончена':'',whole(p.editionsCount)?whole(p.editionsCount)+' '+plural(whole(p.editionsCount),EDITION):''].filter(Boolean).join(' · '),ruler:null};
 }
 return {figures:[],note:'',ruler:null};
}

