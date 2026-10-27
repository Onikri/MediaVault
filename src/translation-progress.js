// Status comes from observed pipeline events. Time is not a progress estimate.
export function normalizeTranslationProgress(value){
 if(typeof value==='string')return {message:value};
 if(!value||typeof value!=='object')return {message:''};
 const result={...value,message:typeof value.message==='string'?value.message.slice(0,600):''};
 if(Number.isFinite(value.retryAtMs)&&Number.isFinite(value.serverTimeMs))result.retryAtMs=(Number.isFinite(value.clientReceivedAt)?value.clientReceivedAt:Date.now())+Math.max(0,value.retryAtMs-value.serverTimeMs);
 return result;
}
export function translationDuration(ms){const seconds=Math.max(0,Math.floor(ms/1000));return seconds<60?seconds+' с':Math.floor(seconds/60)+' мин '+String(seconds%60).padStart(2,'0')+' с';}
export function translationProgressDetails(progress,now=Date.now()){
 if(!progress)return [];
 const parts=[];
 if(progress.page)parts.push('Страница '+progress.page);
 if(progress.model)parts.push(progress.model==='gemma-4-31b-it'?'Gemma 4 · 31B':progress.model==='gemma-4-26b-a4b-it'?'Gemma 4 · 26B':progress.model);
 if(Number.isInteger(progress.totalRegions)&&progress.totalRegions>0)parts.push('Обработано '+Math.min(progress.totalRegions,progress.completedRegions||0)+' / '+progress.totalRegions);
 if(progress.attempt>0)parts.push('Запрос '+progress.attempt);
 if(progress.running&&progress.startedAt)parts.push('Прошло '+translationDuration(now-progress.startedAt));
 if(progress.running&&progress.retryAtMs>now)parts.push('Повтор через '+Math.ceil((progress.retryAtMs-now)/1000)+' с');
 return parts;
}
