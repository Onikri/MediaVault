// A ranobe or book saved as one file: EPUB 3 (chapters, table of contents,
// cover) or plain text. Chapters come from the same server route the reader
// uses, three at a time; a chapter that fails is retried, then named in the
// file instead of silently dropped.
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'})[c]);
const paragraphText=p=>typeof p==='string'?p:String(p?.text||p?.content||'');
export const safeFileName=value=>String(value||'Книга').replace(/[\\/:*?"<>|\u0000-\u001f]+/g,' ').replace(/\s+/g,' ').trim().slice(0,120)||'Книга';

export async function loadChapters(entries,load,{signal,onProgress=()=>{},concurrency=3,attempts=3}={}){
 const results=new Array(entries.length);let next=0,done=0;
 async function worker(){
  while(next<entries.length){
   const index=next++,entry=entries[index];
   for(let attempt=1;;attempt++){
    signal?.throwIfAborted();
    try{const value=await load(entry,signal);results[index]={entry,title:value.title||entry.title||'',paragraphs:(value.paragraphs||[]).map(paragraphText).filter(Boolean)};break;}
    catch(error){
     if(signal?.aborted||error?.name==='AbortError')throw error;
     if(attempt>=attempts){results[index]={entry,title:entry.title||'',paragraphs:[],error:error?.message||'Глава не загрузилась'};break;}
     await new Promise(r=>setTimeout(r,800*attempt));
    }
   }
   onProgress({done:++done,total:entries.length,failed:results.filter(r=>r?.error).length});
  }
 }
 await Promise.all(Array.from({length:Math.min(concurrency,entries.length)},worker));
 return results;
}
const chapterHeading=row=>{const n=row.entry.number,t=String(row.title||'').trim();return t&&!/^(глава|chapter)\s*[\d.]+$/i.test(t)?(n!=null?'Глава '+n+'. ':'')+t:'Глава '+(n??'');};

export function textFile({title,authors=[],source,chapters}){
 const lines=[title,authors.join(', '),source?'Источник: '+source:'',''];
 for(const row of chapters){lines.push('','',chapterHeading(row),'');if(row.error)lines.push('[Глава не загрузилась: '+row.error+']');else lines.push(...row.paragraphs.map(p=>p+'\n'));}
 return new Blob([lines.filter((v,i)=>i>3||v).join('\n')],{type:'text/plain;charset=utf-8'});
}

export async function epubFile({title,authors=[],language='ru',source,description,cover,chapters,identifier}){
 const {default:JSZip}=await import('jszip');
 const zip=new JSZip(),id=identifier||'urn:uuid:'+(crypto.randomUUID?.()||Date.now().toString(36));
 zip.file('mimetype','application/epub+zip',{compression:'STORE'});
 zip.file('META-INF/container.xml','<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>');
 let coverItem='';
 if(cover){
  try{const response=await fetch(cover,{referrerPolicy:'no-referrer'});const type=response.headers.get('content-type')||'';if(response.ok&&/^image\/(jpeg|png|webp)/.test(type)){const ext=type.includes('png')?'png':type.includes('webp')?'webp':'jpg';zip.file('OEBPS/cover.'+ext,await response.arrayBuffer());coverItem=`<item id="cover-image" href="cover.${ext}" media-type="${type.split(';')[0]}" properties="cover-image"/>`;}}catch{}
 }
 const page=(heading,body)=>`<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="${escape(language)}" lang="${escape(language)}"><head><meta charset="UTF-8"/><title>${escape(heading)}</title><style>body{font-family:serif;line-height:1.6;margin:0 5%}h1{font-size:1.4em;margin:1.5em 0 1em}p{text-indent:1.5em;margin:0 0 .4em}</style></head><body>${body}</body></html>`;
 zip.file('OEBPS/title.xhtml',page(title,`<h1>${escape(title)}</h1>${authors.length?`<p>${escape(authors.join(', '))}</p>`:''}${description?`<p>${escape(description)}</p>`:''}${source?`<p>Источник: ${escape(source)}</p>`:''}`));
 chapters.forEach((row,i)=>{const heading=chapterHeading(row);zip.file(`OEBPS/c${i+1}.xhtml`,page(heading,`<section epub:type="chapter"><h1>${escape(heading)}</h1>${row.error?`<p>[Глава не загрузилась: ${escape(row.error)}]</p>`:row.paragraphs.map(p=>`<p>${escape(p)}</p>`).join('')}</section>`));});
 zip.file('OEBPS/nav.xhtml',page('Оглавление',`<nav epub:type="toc"><h1>Оглавление</h1><ol>${chapters.map((row,i)=>`<li><a href="c${i+1}.xhtml">${escape(chapterHeading(row))}</a></li>`).join('')}</ol></nav>`));
 const modified=new Date().toISOString().replace(/\.\d+Z$/,'Z');
 zip.file('OEBPS/content.opf',`<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="${escape(language)}"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">${escape(id)}</dc:identifier><dc:title>${escape(title)}</dc:title><dc:language>${escape(language)}</dc:language>${authors.map(a=>`<dc:creator>${escape(a)}</dc:creator>`).join('')}${source?`<dc:source>${escape(source)}</dc:source>`:''}<meta property="dcterms:modified">${modified}</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>${coverItem}${chapters.map((_,i)=>`<item id="c${i+1}" href="c${i+1}.xhtml" media-type="application/xhtml+xml"/>`).join('')}</manifest><spine><itemref idref="title"/><itemref idref="nav"/>${chapters.map((_,i)=>`<itemref idref="c${i+1}"/>`).join('')}</spine></package>`);
 return zip.generateAsync({type:'blob',mimeType:'application/epub+zip',compression:'DEFLATE'});
}

export function saveBlob(blob,name){
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
}
