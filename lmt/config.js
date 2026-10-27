// SPDX-License-Identifier: AGPL-3.0-or-later
export function validateConfig(config={}){
 if(!config.allowDownloads)throw Error('Разреши загрузку моделей в настройках LMT.');
 if(!['English','Japanese','Korean','Chinese (Simplified)'].includes(config.language||'English'))throw Error('Выбери исходный язык страницы.');
 const vision=config.mode==='gemma'||config.mode==='api'&&config.apiInput==='vision';
 if(!vision&&config.ocr==='ppocrv5-korean'&&config.language!=='Korean')throw Error('PP-OCRv5 Korean предназначен для корейского языка.');
 if(!vision&&['ppocrv6-manga','manga-ocr'].includes(config.ocr)&&config.language!=='Japanese')throw Error('Этот OCR предназначен для японского языка. Выбери PaddleOCR.');
 if(!vision&&config.ocr==='pororo'&&config.language!=='Korean')throw Error('Pororo предназначен для корейского языка. Выбери PaddleOCR.');
 if(config.apiKey&&/[^\x21-\x7e]/.test(config.apiKey))throw Error('Ключ своего сервера содержит пробелы или недопустимые символы.');
 if(config.mode==='api'){
  let endpoint;try{endpoint=new URL(config.host);}catch{throw Error('Укажи адрес своего LLM-сервера, например https://…/v1.');}
  if(endpoint.username||endpoint.password||!['https:','http:'].includes(endpoint.protocol)||endpoint.search||endpoint.hash)throw Error('Некорректный адрес своего сервера.');
  if(endpoint.protocol==='http:'&&!['localhost','127.0.0.1','[::1]'].includes(endpoint.hostname))throw Error('Для удалённого сервера нужен HTTPS.');
  if(!String(config.serverModel||'').trim())throw Error('Укажи имя модели своего сервера.');
 }
}
