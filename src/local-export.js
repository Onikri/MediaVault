import {mangaExportJobs} from './manga-export-client.js';
export async function exportLocally({entries,kind,referer,quality='best',service,onProgress=()=>{},signal,manga,cacheContext}){
 if(!entries.length)throw Error('Выбери опубликованную главу или серию.');
 if(Number(service.session?.serverVersion)<16)throw Error('Для сохранения на устройство обнови сервер до версии 16.');
 if(manga&&Number(service.session?.serverVersion)<50)throw Error('Для перевода перед скачиванием нужен сервер версии 50.');
 if(manga)onProgress('Проверяем настройки и готовые страницы в кэше…');
 const tasks=manga?await mangaExportJobs(entries,{...manga,quality},cacheContext):entries.map(entry=>({body:{url:entry.url,kind,quality,...(kind==='video'&&referer?{referer}:{})},uploads:[]}));
 if(!tasks.length)throw Error('В выбранном интервале нет глав.');
 const downloads=[];
 for(let index=0;index<tasks.length;index++){
  signal?.throwIfAborted();let job;
  try{
   onProgress('Подготавливаем '+(index+1)+' / '+tasks.length+'…');
   job=await service.request('/online/exports',{method:'POST',body:tasks[index].body,signal});
   if(job.state==='staging'){
    for(const [number,page] of tasks[index].uploads.entries()){
     signal?.throwIfAborted();onProgress((page.source?'Передаём исходные страницы':'Передаём готовые страницы из кэша')+' · '+(number+1)+' / '+tasks[index].uploads.length);
     await service.request('/online/exports/'+job.id+'/pages/'+page.chapter+'/'+page.page+(page.source?'?source=1':''),{method:'PUT',body:page.blob,signal});
    }
    job=await service.request('/online/exports/'+job.id+'/start',{method:'POST',signal});
   }
   while(['queued','running'].includes(job.state)){
    await new Promise((resolve,reject)=>{const stop=()=>{clearTimeout(timer);reject(signal.reason);};const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},1000);signal?.addEventListener('abort',stop,{once:true});});
    job=await service.request('/online/exports/'+job.id,{signal});
    const p=job.progress||{};onProgress('Файл '+(index+1)+' / '+tasks.length+(p.chapter?' · глава '+p.chapter+' / '+p.chaptersTotal:'')+(p.phase==='translating'?' · перевод на ВМ':'')+(p.pagesTotal?' · страницы '+(p.pagesLoaded||0)+' / '+p.pagesTotal:p.phase==='assembling'?' · собираем файл':' · загружаем из источника')+(p.message?' · '+p.message:''));
   }
   if(job.state!=='done'||!job.downloadUrl)throw Error(job.error||'Не удалось подготовить файл.');
   const url=new URL(job.downloadUrl,service.server);if(url.origin!==new URL(service.server).origin||!url.pathname.startsWith('/online/exports/file/'))throw Error('Сервер вернул некорректную ссылку сохранения.');
   const anchor=document.createElement('a');anchor.href=url.href;anchor.download=job.filename||'';anchor.rel='noreferrer';document.body.append(anchor);anchor.click();anchor.remove();downloads.push({url:url.href,name:job.filename});
  }catch(error){if(job?.id&&['staging','queued','running'].includes(job.state))await service.request('/online/exports/'+job.id,{method:'DELETE'}).catch(()=>{});throw error;}
 }
 return downloads;
}
