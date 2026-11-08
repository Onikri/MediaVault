// Pure ru→uk lookup used by the DOM layer. Interface strings are matched in
// three steps: the whole string, the string with its numbers as {0},{1}…, then
// known phrases inside a short composed string ("Аня, играет", "12 серий").
// Long text without an exact entry is treated as content and left untouched.
const CYRILLIC=/[А-Яа-яЁё]/;
const EDGE=/^[\s.,:;!?·—–\-…()«»"“”'„]+|[\s.,:;!?·—–\-…()«»"“”'„]+$/g;
const LETTER='\\p{L}\\p{M}';
export const PHRASE_LIMIT=400;

function capitalize(value){return value.charAt(0).toLocaleUpperCase('uk')+value.slice(1);}
function lowerFirst(value){return value.charAt(0).toLocaleLowerCase('uk')+value.slice(1);}
const escape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');

export function createTranslator(dictionary){
 const exact=new Map(Object.entries(dictionary||{}));
 const phrases=new Map();
 for(const [source,target] of exact){
  if(/\{\d+\}/.test(source))continue;
  const key=source.replace(EDGE,''),value=String(target).replace(EDGE,'');
  // Single short words are too ambiguous inside composed strings.
  if(!CYRILLIC.test(key)||!value||key.length<3||key.length>120)continue;
  if(!phrases.has(key))phrases.set(key,value);
  const lower=lowerFirst(key),upper=capitalize(key);
  if(lower!==key&&!phrases.has(lower)&&!exact.has(lower))phrases.set(lower,lowerFirst(value));
  if(upper!==key&&!phrases.has(upper)&&!exact.has(upper))phrases.set(upper,capitalize(value));
 }
 const keys=[...phrases.keys()].sort((a,b)=>b.length-a.length);
 const pattern=keys.length?new RegExp('(?<!['+LETTER+'])(?:'+keys.map(escape).join('|')+')(?!['+LETTER+'])','gu'):null;
 const cache=new Map();
 function lookup(core){
  if(exact.has(core))return exact.get(core);
  const numbers=[];
  const template=core.replace(/\d+(?:[.,]\d+)?/g,match=>'{'+(numbers.push(match)-1)+'}');
  if(numbers.length&&exact.has(template))return exact.get(template).replace(/\{(\d+)\}/g,(m,i)=>numbers[i]??m);
  if(!pattern||core.length>PHRASE_LIMIT)return null;
  let changed=false;
  const result=core.replace(pattern,match=>{changed=true;return phrases.get(match);});
  return changed?result:null;
 }
 return function translate(text){
  if(typeof text!=='string'||!CYRILLIC.test(text))return text;
  if(cache.has(text))return cache.get(text);
  const start=text.length-text.trimStart().length,end=text.trimEnd().length;
  const core=text.slice(start,end).replace(/\s+/g,' ');
  const found=lookup(core);
  const value=found==null?text:text.slice(0,start)+found+text.slice(end);
  if(cache.size>4000)cache.delete(cache.keys().next().value);
  cache.set(text,value);
  return value;
 };
}
