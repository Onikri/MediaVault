// Browser playback errors are intentionally separated from decryption and
// codec errors. Never log access tokens, Drive URLs, or decrypted media.
const MEDIA_ERROR = {
  1: 'Воспроизведение прервано.',
  2: 'Сетевая ошибка при чтении видео.',
  3: 'Не удалось декодировать файл: он повреждён или использует неподдерживаемый кодек.',
  4: 'Браузер не поддерживает видеоконтейнер или кодеки этого файла.'
};
export function describeMediaError(code) {
  return MEDIA_ERROR[code] || 'Не удалось воспроизвести видео.';
}
export function recognizeVideoCodec(bytes) {
  if(!(bytes instanceof Uint8Array))return '';
  const head=bytes.subarray(0,Math.min(bytes.byteLength,512*1024));
  let text='';
  const part=16384;
  for(let i=0;i<head.length;i+=part)text+=String.fromCharCode(...head.subarray(i,i+part));
  if(/hvc1|hev1/i.test(text))return 'HEVC / H.265';
  if(/av01/i.test(text))return 'AV1';
  if(/vp09/i.test(text))return 'VP9';
  if(/ac-3|ec-3/i.test(text))return 'Dolby AC-3 / E-AC-3';
  return '';
}
export async function diagnoseVideoFailure({video,source,signal}) {
  const original=describeMediaError(video?.error?.code);
  if(!source)return original+' Поток недоступен. Проверь подключение к Google Drive.';
  try{
    const response=await fetch(source,{method:'HEAD',cache:'no-store',signal});
    if(!response.ok){
      if(response.status===503)return 'Служба потокового просмотра не получила доступ к Google Drive или не смогла расшифровать файл. Подключи Drive заново и обнови библиотеку.';
      if(response.status===404)return 'Видео отсутствует в текущей расшифрованной библиотеке. Обнови каталог.';
      return 'Ошибка источника видео: HTTP '+response.status+'. Попробуй повторно подключить Drive.';
    }
    // HEAD succeeds even when the browser cannot decode its codec.
    // Inspect a tiny range locally, never upload decrypted bytes.
    if(video?.error?.code===3||video?.error?.code===4){
      try{
        const partial=await fetch(source,{headers:{Range:'bytes=0-65535'},cache:'no-store',signal});
        if(partial.ok){
          const codec=recognizeVideoCodec(new Uint8Array(await partial.arrayBuffer()));
          if(codec)return 'Этот файл содержит '+codec+'. Возможно, браузер не умеет воспроизводить этот кодек. Перекодируй видео в MP4 H.264 + AAC.';
        }
      }catch(error){if(error?.name==='AbortError')throw error;}
      return original+' Для максимальной совместимости используй MP4 (H.264 + AAC).';
    }
    return original+' Попробуй резервную загрузку файла или обнови доступ к Drive.';
  }catch(error){
    if(error?.name==='AbortError')return original;
    return original+' Сетевой запрос к потоку завершился ошибкой; проверь соединение и Service Worker.';
  }
}
