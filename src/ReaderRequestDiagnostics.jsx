import {useState} from 'react';
import {safeDiagnosticExport} from './google-request-diagnostics.js';
const bytes=n=>!Number.isFinite(n)?'—':n<1024?n+' Б':n<1024*1024?(n/1024).toFixed(1)+' КБ':(n/1024/1024).toFixed(2)+' МБ';
const time=n=>Number.isFinite(n)?(n/1000).toFixed(3)+' с':'не сообщено браузером';
export default function ReaderRequestDiagnostics({value:d,now}){
 const [message,setMessage]=useState('');if(!d)return null;
 const m=d.metrics||{},l=d.local||{},usage=d.usage||d.response?.usageMetadata;
 const rows=[['Очередь на устройстве',l.queueMs],['Чтение в очереди перевода',l.sourceReadMs],['Проверка кэша / SHA',l.fingerprintAndCacheMs],['Подготовка страницы целиком',l.clientPreparationMs],['Декодирование изображения',l.decodeMs],['Поиск блоков',l.detectMs],['Метки и сжатие',Number.isFinite(l.markMs)&&Number.isFinite(l.encodeMs)?l.markMs+l.encodeMs:undefined],['Подготовка JSON запроса',m.requestBuildMs],['До конца отправки · с соединением/CORS',m.uploadMs],['До заголовков ответа',m.headersMs],['Ожидание после отправки',m.waitAfterUploadMs],['До первого блока ответа',m.firstByteMs],['Получение тела ответа',m.downloadMs],['Разбор JSON',m.parseMs],['Проверка перевода',m.validationMs],['Google целиком',m.googleTotalMs],['Очистка',l.inpaintMs],['Набор текста',l.typesetMs],['Рендер целиком',l.renderMs],['Весь перевод',l.totalMs]];
 function download(){const blob=new Blob([JSON.stringify(d.requestBody,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='mediavault-google-request.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 async function copy(){try{await navigator.clipboard.writeText(JSON.stringify(safeDiagnosticExport(d),null,2));setMessage('Отчёт скопирован. API-ключ исключён.');}catch{setMessage('Не удалось скопировать. Выдели JSON ниже.');}}
 return <details className="reader-request-diagnostics"><summary>Запрос Google и подробные метрики</summary><div className="reader-request-body">
  <p><strong>{d.model}</strong> · {d.pages} стр. · {d.boxes} блоков · HTTP {d.httpStatus||'не получен'}</p>
  <p>JSON запроса: <strong>{bytes(d.requestBytes)}</strong> / {bytes(d.limitBytes)} inline-данных. Максимум ответа: {d.requestBody?.generationConfig?.maxOutputTokens} токенов. Квота запросов и токенов в минуту зависит от проекта Google.</p>
  {d.modelInputLimit&&<p>Лимиты модели по документации: вход {d.modelInputLimit.toLocaleString('ru-RU')} токенов, выход {d.modelOutputLimit?.toLocaleString('ru-RU')}. Это размер контекста, не минутная квота ключа.</p>}
  {m.sentAt&&d.stage!=='ready'&&d.stage!=='complete'&&d.stage!=='error'&&<p role="status">С начала отправки: {Math.max(0,(now-m.sentAt)/1000).toFixed(1)} с · тайм-аут {d.timeoutMs/1000} с{Number.isFinite(m.uploadLoaded)?' · отправлено '+bytes(m.uploadLoaded)+(m.uploadTotal?' / '+bytes(m.uploadTotal):''):''}</p>}
  <dl>{rows.map(([name,n])=><div key={name}><dt>{name}</dt><dd>{time(n)}</dd></div>)}</dl>
  <p className="reader-hint">Отсчёт начинается после получения исходника читалкой. Браузер не отделяет время соединения/CORS от отправки, а работу модели — от сетевого ожидания. Неизмеренные значения показаны прочерком или пометкой, без выдуманной скорости.</p>
  {usage&&<p>Токены Google: вход {usage.promptTokenCount??'—'} · ответ {usage.candidatesTokenCount??'—'} · размышления {usage.thoughtsTokenCount??'—'} · всего {usage.totalTokenCount??'—'}. Завершение: {d.finishReason||d.response?.candidates?.[0]?.finishReason||'—'}.</p>}
  {d.error&&<p className="reader-request-error">{d.error}</p>}
  <details><summary>Что именно отправляется</summary><p>{d.method} {d.endpoint}</p><p>Заголовок x-goog-api-key скрыт. Координаты ниже хранятся на устройстве; Google получает метки ID и размеченный скан.</p><pre>{JSON.stringify(d.requestPreview,null,2)}</pre><button type="button" onClick={download}>Скачать полный JSON запроса</button><pre>{JSON.stringify(d.coordinates,null,2)}</pre></details>
  <details><summary>Изображения и размеры</summary>{d.images.map((image,i)=><figure key={image.id}><figcaption>{image.id} · {image.width}×{image.height} → {image.sentWidth}×{image.sentHeight} · {image.mime} · {bytes(image.bytes)} · {image.regions} блоков</figcaption><img loading="lazy" src={'data:'+image.mime+';base64,'+d.requestBody.contents[0].parts.filter(p=>p.inlineData)[i].inlineData.data} alt={'Скан '+image.id+', отправленный Google'}/></figure>)}</details>
  <details><summary>Ответ Google и причины отказа</summary><pre>{JSON.stringify(d.response||{status:d.stage,error:d.error||'Ответ ещё не получен'},null,2)}</pre></details>
  <button type="button" onClick={copy}>Скопировать отчёт без API-ключа</button>{message&&<small role="status">{message}</small>}
 </div></details>;
}
