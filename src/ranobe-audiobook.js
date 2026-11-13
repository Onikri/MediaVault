// Ranobe/book chapters saved as an audiobook from the title page's save window,
// on this device. Every chapter is voiced exactly as in the reader: the title
// bible, the director's role pass, the cast and the listener's voice choices
// (tts/chapter-script.js), Gemini 2.5 Flash Native Audio through the server.
// Chapters are read and voiced one at a time and each becomes its own file as
// soon as it is ready, so a stopped save keeps the chapters already made. The
// VM does the same for Google Drive (narration-export.html + server/ranobe_audiobook.py).
import {createClipStore,chapterAudio,audiobookWriter,audiobookFileName} from './tts/audiobook.js';

// Languages the server's narration prompt reads (gemini_voice.LANGUAGE).
export const AUDIOBOOK_LANGUAGES=['ru','uk'];
const silence=(seconds,rate)=>new Float32Array(Math.round(seconds*rate));

// prepare(entry) → {title, rows, analysis} for one chapter (its text loaded and
// directed); a chapter whose text does not load is skipped and counted.
// save(blob, name) is called once per finished chapter.
export async function saveChapterAudiobooks({entries,book,language='ru',signal,save,prepare,make,onProgress=()=>{},writer=audiobookWriter}){
 const files=[],partial=[];let failed=0;
 for(const [index,entry] of entries.entries()){
  signal?.throwIfAborted?.();
  onProgress({chapter:index+1,chapters:entries.length,phase:'script',files:files.length});
  let chapter;
  try{chapter=await prepare(entry);}
  catch(error){if(signal?.aborted||error?.name==='AbortError')throw error;failed++;continue;}
  signal?.throwIfAborted?.();
  const heading=String(chapter.title||entry.title||'').trim();
  if(chapter.analysis==='failed')throw Object.assign(Error('Google не разметил роли главы «'+(heading||index+1)+'» — похоже, закончилась квота. Готовые главы сохранены, повтори позже.'),{saved:files});
  if(chapter.analysis==='partial')partial.push(heading||String(index+1));
  if(!chapter.rows?.length){failed++;continue;}
  const tags={title:heading,album:book.title,artist:(book.authors||[]).join(', '),genre:'Audiobook',language,comment:'Синтезированная озвучка MediaVault: Gemini 2.5 Flash Native Audio'};
  let file=null;
  try{
   for await(const part of chapterAudio({rows:chapter.rows,language,store:createClipStore(),make,signal,ahead:2,
    onProgress:value=>onProgress({chapter:index+1,chapters:entries.length,phase:'voice',phrases:value.done,phrasesTotal:value.total,files:files.length})})){
    file||=await writer(part.sampleRate,{tags});
    await file.write(part.audio);
    await file.write(silence(part.row.pause||0,file.rate));
    signal?.throwIfAborted?.();
   }
   const name=audiobookFileName(book.title,heading,file.ext);
   await save(await file.finish(),name);files.push(name);
  }catch(error){file?.close();throw Object.assign(error,{saved:files});}
 }
 return {files,failed,partial};
}
