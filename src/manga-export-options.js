import {chapterRanges} from './manga-import.js';
export const defaultMangaExport={mode:'original',format:'cbz',grouping:'chapters',volumes:''};
export function exportBundles(entries,options,name='Манга'){
 const ranges=chapterRanges(options.volumes),selected=entries.filter(e=>!ranges||ranges.some(([a,b])=>Number(e.season||1)>=a&&Number(e.season||1)<=b));
 const ordered=[...selected].sort((a,b)=>Number(a.season||1)-Number(b.season||1)||a.number-b.number);
 const groups=options.grouping==='single'?[ordered]:options.grouping==='volumes'?[...Map.groupBy(ordered,e=>Number(e.season||1)).values()]:ordered.map(e=>[e]);
 return groups.filter(g=>g.length).map(group=>({entries:group,name:(name+(options.grouping==='single'?'':options.grouping==='volumes'?' · Том '+(group[0].season||1):' · Том '+(group[0].season||1)+' · Глава '+group[0].number)).slice(0,180)}));
}
export function exportTranslation(settings={},language){
 const allowed=['directModel','language','direction','directInput','directDetector','directBatchPages','inpaint','font'];
 return Object.fromEntries(allowed.map(k=>[k,settings[k]]).filter(([,v])=>v!==undefined).concat(language?[['language',language]]:[]));
}
