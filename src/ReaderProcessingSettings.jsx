import {useEffect,useState} from 'react';

export default function ReaderProcessingSettings({value={},onChange,service}){
 const [capabilities,setCapabilities]=useState(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  if(!service?.server&&!service?.request)return;
  const abort=new AbortController();setCapabilities(null);setError('');
  service.request('/reader/processing',{auth:false,signal:abort.signal}).then(setCapabilities).catch(e=>{if(!abort.signal.aborted)setError(e.status===404?'Обнови backend: обработчик MangaJaNai ещё не установлен.':e.message);});
  return()=>abort.abort();
 },[service?.server,attempt]);
 const set=patch=>onChange({...value,...patch});
 return <details className="lmt-settings reader-upscale-settings">
  <summary>MangaJaNai · качество страниц</summary>
  <p className="reader-hint">Нейросеть обрабатывает видимые страницы на твоём backend. Оригинал в библиотеке сохраняется.</p>
  <label className="reader-checkbox"><input type="checkbox" checked={!!value.enabled} onChange={e=>set({enabled:e.target.checked})}/>Включить MangaJaNai</label>
  <label>Масштаб<select aria-label="Масштаб MangaJaNai" value={value.scale||2} onChange={e=>set({scale:Number(e.target.value)})}><option value="1">1× · удаление JPEG-артефактов</option><option value="2">2×</option><option value="4">4×</option></select></label>
  <label>Страницы<select aria-label="Тип страниц MangaJaNai" value={value.content||'auto'} onChange={e=>set({content:e.target.value})}><option value="auto">Определять цвет автоматически</option><option value="mono">Чёрно-белая манга</option><option value="color">Цветные · IllustrationJaNai</option></select></label>
  <label>Модель<select aria-label="Модель MangaJaNai" value={value.model||'auto'} onChange={e=>set({model:e.target.value})}><option value="auto">Автовыбор по цвету и высоте</option>{capabilities?.upscale?.models?.map(model=><option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
  <label>Тайл<select aria-label="Размер тайла MangaJaNai" value={value.tile||256} onChange={e=>set({tile:Number(e.target.value)})}>{[64,128,256,512].map(n=><option key={n} value={n}>{n} px{n===128?' · меньше памяти':''}</option>)}</select></label>
  <p className="reader-hint" role="status">{error||(capabilities?(capabilities.upscale?.ready?`Установлено моделей: ${capabilities.upscale.models.length}. LMT: ${capabilities.lmt?.ready?'готов':'требуется настройка на backend'}.`:'Установи модели MangaJaNai на backend.'):service?.request?'Проверяем модели backend…':'Подключи backend в профиле владельца.')}</p>
  <button type="button" onClick={()=>setAttempt(n=>n+1)}>Проверить модели</button>
  <p className="reader-hint"><a href="https://github.com/the-database/MangaJaNai" target="_blank" rel="noopener noreferrer">MangaJaNai</a> · CC BY-NC 4.0</p>
 </details>;
}
