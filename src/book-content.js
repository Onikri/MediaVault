export function splitBookText(text,limit=4200){
 const paragraphs=String(text||'').replace(/\r\n?/g,'\n').split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean),pages=[];let current='';
 for(const paragraph of paragraphs){
  if(current.length+paragraph.length>limit&&current){pages.push(current);current='';}
  if(paragraph.length>limit){const words=paragraph.split(/\s+/);for(const word of words){if(current.length+word.length>limit&&current){pages.push(current);current='';}current+=(current?' ':'')+word;}}
  else current+=(current?'\n\n':'')+paragraph;
 }
 if(current)pages.push(current);return pages;
}
export function decodeBookText(buffer){const bytes=new Uint8Array(buffer);try{return new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{return new TextDecoder('windows-1251').decode(bytes);}}
const key=(user,library,item)=>'mediavault_book_progress_v1:'+encodeURIComponent(user||'anonymous')+':'+encodeURIComponent(library||'local')+':'+encodeURIComponent(item);
export function bookProgress(user,library,item,storage=globalThis.localStorage){try{const value=JSON.parse(storage.getItem(key(user,library,item))||'null');return value&&typeof value==='object'?value:null;}catch{return null;}}
export function saveBookProgress(user,library,item,value,storage=globalThis.localStorage){try{storage.setItem(key(user,library,item),JSON.stringify({...value,updatedAt:Date.now()}));}catch{}}
export function bookPreferences(user,storage=globalThis.localStorage){try{return normalizeBookPreferences(JSON.parse(storage.getItem('mv_book_preferences:'+encodeURIComponent(user||'anonymous'))||'{}'));}catch{return normalizeBookPreferences();}}
export function normalizeBookPreferences(value={}){return {theme:['paper','dark','black'].includes(value.theme)?value.theme:'paper',font:['serif','sans'].includes(value.font)?value.font:'serif',size:[16,18,20,22,24,28].includes(+value.size)?+value.size:20,width:[560,720,900,1100].includes(+value.width)?+value.width:720,lineHeight:[1.5,1.75,2].includes(+value.lineHeight)?+value.lineHeight:1.75,mode:value.mode==='scroll'?'scroll':'pages'};}
export function saveBookPreferences(user,value,storage=globalThis.localStorage){try{storage.setItem('mv_book_preferences:'+encodeURIComponent(user||'anonymous'),JSON.stringify(normalizeBookPreferences(value)));}catch{}}
export function fictionBook(text){
 const xml=new DOMParser().parseFromString(text,'application/xml');if(xml.querySelector('parsererror')||xml.doctype)throw Error('Не удалось прочитать FB2. Открой файл без ошибок XML и внешних сущностей.');
 const body=[...xml.getElementsByTagName('body')].find(node=>node.getAttribute('name')!=='notes');if(!body)throw Error('В FB2 нет текста книги.');
 const sections=[...body.children].filter(node=>node.localName==='section');const rows=sections.length?sections:[body];
 return rows.flatMap((section,i)=>{const heading=[...section.children].find(n=>n.localName==='title')?.textContent?.trim()||'Глава '+(i+1);const paragraphs=[...section.querySelectorAll('p,subtitle,text-author')].map(n=>n.textContent.trim()).filter(Boolean);return splitBookText(paragraphs.join('\n\n')).map((content,j)=>({title:heading+(j?' · продолжение':''),content}));});
}

export function bookPageCapacity(width,height,size=20,lineHeight=1.75){const columns=Math.max(12,Math.floor((width-70)/(size*.56))),lines=Math.max(6,Math.floor((height-100)/(size*lineHeight)));return Math.max(150,Math.floor(columns*lines*.82));}
export function paginateBookRows(rows,capacity){return rows.flatMap(row=>splitBookText(row.content,capacity).map(content=>({...row,content})));}
export function pageAtOffset(pages,offset=0){let count=0;for(let i=0;i<pages.length;i++){count+=pages[i].content.length;if(count>offset)return i;}return Math.max(0,pages.length-1);}
