// Light-novel sources served by the MediaVault server (/ranobe/*).
// Chapter text stays in memory only; progress stores a chapter URL and a
// paragraph index per profile and book, never chapter text.
const chapters=new Map();
const LIMIT=24;

export function ranobeTitle(item){
 return {id:item.id,title:item.title,titles:item.titles||{},aliases:item.aliases||[],ids:item.ids||{},year:item.year,kind:item.kind==='book'?'book':'ranobe',...(item.kind==='book'?{authors:(item.authors||[]).slice(0,4)}:{})};
}
export async function searchRanobe(service,item,language,{signal}={}){
 return service.request('/ranobe/search',{method:'POST',body:{title:ranobeTitle(item),language},signal});
}
export async function inspectRanobe(service,url,item,{signal}={}){
 return service.request('/ranobe/inspect',{method:'POST',body:{url,...(item?{title:ranobeTitle(item)}:{})},signal});
}
export async function readRanobeChapter(service,url,item,{signal}={}){
 if(chapters.has(url)){const value=chapters.get(url);chapters.delete(url);chapters.set(url,value);return value;}
 const value=await service.request('/ranobe/chapter',{method:'POST',body:{url,...(item?{title:ranobeTitle(item)}:{})},signal});
 if(!Array.isArray(value?.paragraphs))throw Error('Источник вернул главу без текста.');
 chapters.set(url,value);while(chapters.size>LIMIT)chapters.delete(chapters.keys().next().value);
 return value;
}

const key=(user,book)=>'mediavault_ranobe_progress_v1:'+encodeURIComponent(user||'anonymous')+':'+encodeURIComponent(book);
export function ranobeProgress(user,book,storage=globalThis.localStorage){
 try{const value=JSON.parse(storage.getItem(key(user,book))||'null');return value&&typeof value.chapter==='string'?value:null;}catch{return null;}
}
export function saveRanobeProgress(user,book,value,storage=globalThis.localStorage){
 try{storage.setItem(key(user,book),JSON.stringify({chapter:String(value.chapter),paragraph:Math.max(0,Number(value.paragraph)||0),title:String(value.title||'').slice(0,200),updatedAt:Date.now()}));}catch{}
}
export const providerLanguage=code=>({uk:'Українська',ru:'Русский',en:'English',ja:'日本語',ko:'한국어',und:'Язык уточняется'})[code]||code?.toUpperCase()||'';

// The open reader lives in the page address (#watch=…&read=N), so a reload
// returns to reading instead of the title page. The exact chapter and
// paragraph come from the saved progress of the book.
export function readerInAddress(hash=globalThis.location?.hash||''){const value=Number(new URLSearchParams(hash.slice(1)).get('read'));return Number.isInteger(value)&&value>0?value-1:-1;}
export function addressWithReader(hash,index){
 const params=new URLSearchParams(hash.slice(1));if(!params.get('watch'))return null;
 if(index>=0)params.set('read',String(index+1));else params.delete('read');
 return '#'+params.toString();
}
