import bundled from '../server/manga-tag-policy.json' with {type:'json'};

export const normalizeTag=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
export function compileMangaPolicy(data){
 if(data?.schemaVersion!==1||!Array.isArray(data.tags)||!Array.isArray(data.excludedTerms)||!Array.isArray(data.excludedPrefixes))throw Error('Неверный формат правил тегов.');
 const rules=new Map(),aliases=new Map(),scoped=new Map(),hidden=new Set();
 const terms=data.excludedTerms.map(normalizeTag),prefixes=data.excludedPrefixes.map(normalizeTag);
 const clean=value=>typeof value==='string'&&value.trim().length>=1&&value.length<=120&&!terms.some(t=>(' '+normalizeTag(value)+' ').includes(' '+t+' '))&&!normalizeTag(value).split(' ').some(w=>prefixes.some(p=>w.startsWith(p)));
 for(const row of data.tags){
  const valid=value=>typeof value==='string'&&value.trim().length>=1&&value.length<=120;
  if(!row.key||normalizeTag(row.key)!==row.key||rules.has(row.key)||!valid(row.label)||!Array.isArray(row.aliases))throw Error('Неверная запись тега.');
  rules.set(row.key,row);
  for(const value of [row.key,row.label,...row.aliases]){const alias=normalizeTag(value);if(!valid(value)||aliases.has(alias)&&aliases.get(alias)!==row.key)throw Error('Неоднозначный алиас тега.');aliases.set(alias,row.key);if(!clean(value))hidden.add(row.key);}
  for(const [domain,values] of Object.entries(row.sourceAliases||{}))for(const value of values){const alias=domain+':'+normalizeTag(value);if(!valid(value)||scoped.has(alias)&&scoped.get(alias)!==row.key)throw Error('Неоднозначный алиас источника.');scoped.set(alias,row.key);if(!clean(value))hidden.add(row.key);}
 }
 const key=(value,source='')=>{const id=clean(value)?scoped.get(source+':'+normalizeTag(value))||aliases.get(normalizeTag(value))||'':'';return hidden.has(id)?'':id;};
 const project=(values,source='')=>[...new Set((Array.isArray(values)?values:[]).map(v=>key(v,source)).filter(Boolean))].map(k=>rules.get(k).label);
 return {data,rules,key,project};
}
let active=compileMangaPolicy(bundled),version=0;
const listeners=new Set();
export const mangaPolicy=()=>active;
export const policyVersion=()=>version;
export const subscribeMangaPolicy=listener=>{listeners.add(listener);return()=>listeners.delete(listener);};
let revision='';
export function setMangaPolicy(data,digest=''){
 if(digest&&digest===revision)return;
 const next=compileMangaPolicy(data);active=next;revision=digest;version++;for(const listener of listeners)listener();
}
export function mangaPolicyFacts(row){
 let source='';try{source=new URL(row.sourceUrl||row.url||'').hostname;}catch{}
 return {...row,genres:active.project(row.genres,source),tags:active.project(row.tags,source)};
}
export function mangaPolicyProfile(profile){return {...profile,genres:active.project(profile?.genres),themes:active.project(profile?.themes)};}
