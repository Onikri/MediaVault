import data from '../server/release-statuses.json' with {type:'json'};

export const releaseStatusOptions=[['','Любой статус'],['released','Уже вышли'],['ongoing','Онгоинг'],['anons','Анонс']];
const aliases=new Map(Object.entries(data).flatMap(([code,values])=>values.map(value=>[value,code])));
export const releaseStatus=value=>aliases.get(String(value||'').trim().toLowerCase().replace(/[_-]/g,' '))||'';

const videoKinds=new Set(['anime','movie','tv']);
export const hasReleaseFilter=kind=>videoKinds.has(kind)||kind==='manga'||kind==='ranobe';

export function catalogueAvailable(item,now=Date.now()){
 const today=new Date(now).toISOString().slice(0,10);
 const year=Number(item.year),start=String(item.startDate||'').slice(0,10);
 const status=item.releaseStatus||releaseStatus(item.statusCode)||releaseStatus(item.status);
 if(year>Number(today.slice(0,4))||start>today||status==='anons')return false;
 if(!videoKinds.has(item.kind))return item.chapterCount!==0;
 if(status==='released')return true;
 const aired=item.episodesAired;
 return Number(aired)>0||Number(item.firstAiringAt)>0&&Number(item.firstAiringAt)*1000<=now||
  (aired==null||Number(aired)>0)&&(year>0&&year<Number(today.slice(0,4))||
   start.length===10&&start<today||start.length===7&&start<today.slice(0,7));
}
