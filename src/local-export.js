export async function exportLocally({entries,kind,referer,quality='best',service,onProgress=()=>{},signal}){
 if(!entries.length)throw Error('Выбери опубликованную главу или серию.');
 if(Number(service.session?.serverVersion)<16)throw Error('Для сохранения на устройство обнови сервер до версии 16.');
 const downloads=[];
 for(let index=0;index<entries.length;index++){
  signal?.throwIfAborted();let job;
  try{
   onProgress('Подготавливаем '+(index+1)+' / '+entries.length+'…');
   job=await service.request('/online/exports',{method:'POST',body:{url:entries[index].url,kind,quality,...(kind==='video'&&referer?{referer}:{})},signal});
   while(['queued','running'].includes(job.state)){
    await new Promise((resolve,reject)=>{const stop=()=>{clearTimeout(timer);reject(signal.reason);};const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},1000);signal?.addEventListener('abort',stop,{once:true});});
    job=await service.request('/online/exports/'+job.id,{signal});
    const p=job.progress||{};onProgress('Файл '+(index+1)+' / '+entries.length+(p.pagesTotal?' · страницы '+(p.pagesLoaded||0)+' / '+p.pagesTotal:p.phase==='assembling'?' · собираем файл':' · загружаем из источника'));
   }
   if(job.state!=='done'||!job.downloadUrl)throw Error(job.error||'Не удалось подготовить файл.');
   const url=new URL(job.downloadUrl,service.server);if(url.origin!==new URL(service.server).origin||!url.pathname.startsWith('/online/exports/file/'))throw Error('Сервер вернул некорректную ссылку сохранения.');
   const anchor=document.createElement('a');anchor.href=url.href;anchor.download=job.filename||'';anchor.rel='noreferrer';document.body.append(anchor);anchor.click();anchor.remove();downloads.push({url:url.href,name:job.filename});
  }catch(error){if(job?.id&&['queued','running'].includes(job.state))await service.request('/online/exports/'+job.id,{method:'DELETE'}).catch(()=>{});throw error;}
 }
 return downloads;
}
