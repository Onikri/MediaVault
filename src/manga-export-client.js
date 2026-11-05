import {cachedChapterPages} from './translation-cache.js';
import {exportBundles,exportTranslation} from './manga-export-options.js';
const digest=async blob=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer())),v=>v.toString(16).padStart(2,'0')).join('');
export async function mangaExportJobs(entries,options,{name,userId,cache,scope,chapter,total}={}){
 const bundles=exportBundles(entries,options,name),jobs=[];
 for(const bundle of bundles){
  if(bundle.entries.length>100)throw Error('Выбери до 100 глав в одном файле.');
  const cached=[],uploads=[],chapters=[];
  for(const [index,entry] of bundle.entries.entries()){
   let saved={pages:[],total:0};
   if(options.mode!=='original')saved=cache||await cachedChapterPages({scope:scope||String(userId||'anonymous')+':online',chapter,url:entry.url,total}).catch(()=>saved);
   if(options.mode==='cached'&&!saved.complete)throw Error('Глава '+entry.number+' переведена не полностью или удалена из кэша. Выбери перевод на ВМ.');
   chapters.push({url:entry.url,number:Number(entry.number??1),volume:Number(entry.season||1),title:(entry.title||'').slice(0,200),pageCount:saved.total||0});
   for(const page of saved.pages){const imageHash=await digest(page.blob);cached.push({chapter:index,page:page.page,sourceHash:page.sourceHash,imageHash});uploads.push({chapter:index,page:page.page,blob:page.blob});}
  }
  if(cached.length>1500)throw Error('Выбери до 1500 страниц в одном файле.');
  // A fully cached local/Drive chapter has no publicly downloadable source.
  const sourceLess=!!cache&&!bundle.entries[0].url;
  jobs.push({body:{kind:'manga',quality:options.mode==='original'?options.quality||'best':'best',manga:{name:bundle.name,format:options.format,mode:sourceLess?'cached':options.mode,chapters:sourceLess?[]:chapters,cached,translation:exportTranslation(options)}},uploads});
 }
 return jobs;
}
