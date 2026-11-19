import data from '../server/release-statuses.json' with {type:'json'};

export const releaseStatusOptions=[['','Любой статус'],['released','Уже вышли'],['ongoing','Онгоинг'],['anons','Анонс']];
const aliases=new Map(Object.entries(data).flatMap(([code,values])=>values.map(value=>[value,code])));
export const releaseStatus=value=>aliases.get(String(value||'').trim().toLowerCase().replace(/[_-]/g,' '))||'';
