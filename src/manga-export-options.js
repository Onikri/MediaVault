import {chapterRanges} from './manga-import.js';
export const defaultMangaExport={mode:'original',format:'cbz',grouping:'chapters',volumes:''};
export function exportBundles(entries,options,name='Манга'){
 const ranges=chapterRanges(options.volumes),selected=entries.filter(e=>!ranges||ranges.some(([a,b])=>Number(e.season||1)>=a&&Number(e.season||1)<=b));
 const ordered=[...selected].sort((a,b)=>Number(a.season||1)-Number(b.season||1)||a.number-b.number);
 const volumes=new Map();for(const entry of ordered){const volume=Number(entry.season||1);if(!volumes.has(volume))volumes.set(volume,[]);volumes.get(volume).push(entry);}
 const groups=options.grouping==='single'?[ordered]:options.grouping==='volumes'?[...volumes.values()]:ordered.map(e=>[e]);
 return groups.filter(g=>g.length).map(group=>({entries:group,name:(name+(options.grouping==='single'?'':options.grouping==='volumes'?' · Том '+(group[0].season||1):' · Том '+(group[0].season||1)+' · Глава '+group[0].number)).slice(0,180)}));
}
// The VM renders saved chapters with the reader's own pipeline, so it gets the
// reader's cleanup (smart: paper fill + MI-GAN over the drawing), capitals and
// the face picked for each voice.
export const EXPORT_INPAINT=['smart','fast','quality','moebius','migan'];
const VOICE=/^[a-z]{1,20}$/,FACE=/^(?:private:)?[\w .()+-]{1,100}$/u;
export function exportTranslation(settings={},language){
 const allowed=['directModel','language','direction','directInput','directDetector','directBatchPages','inpaint','font','caps','voiceFonts'];
 const voiceFonts=settings.voiceFonts&&typeof settings.voiceFonts==='object'?Object.fromEntries(Object.entries(settings.voiceFonts).filter(([k,v])=>VOICE.test(k)&&typeof v==='string'&&FACE.test(v)).slice(0,12)):undefined;
 const cleaned={...settings,voiceFonts:voiceFonts&&Object.keys(voiceFonts).length?voiceFonts:undefined,caps:typeof settings.caps==='boolean'?settings.caps:undefined,...(settings.inpaint&&!EXPORT_INPAINT.includes(settings.inpaint)?{inpaint:'smart'}:{})};
 return Object.fromEntries(allowed.map(k=>[k,cleaned[k]]).filter(([,v])=>v!==undefined).concat(language?[['language',language]]:[]));
}
