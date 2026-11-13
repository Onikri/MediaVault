// The VM runs the reader's own narration director in headless Chromium: the
// title bible, the role pass and the cast come out exactly as in the reader,
// and server/ranobe_audiobook.py voices the rows for Google Drive. Google calls
// go through the page's fixed binding to the owner's server pool.
import {chapterScript} from './tts/chapter-script.js';

window.narrationScript=async({paragraphs,bookKey,chapterKey,meta,direction})=>{
 const service={session:{googleGatewayVersion:5,serverVersion:71},request:(path,request)=>window.exportGoogleRequest(path,request?.body||{})};
 const value=await chapterScript({paragraphs,bookKey,chapterKey,meta,service,userId:'vm-export',direction});
 return {analysis:value.analysis,stats:value.stats,rows:value.rows.map(row=>({text:row.text,voice:row.voice,style:row.style||'',pause:row.pause||0,kind:row.kind||'narration'}))};
};
