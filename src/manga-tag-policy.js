import {hentaiExcluded,hentaiLabel,sourceGenreProjection} from './source-genres.js';
import taxonomy from '../server/catalog-taxonomy.json' with {type:'json'};
import bundled from '../server/manga-tag-policy.json' with {type:'json'};
import {readableCatalogLabel} from './catalog-label.js';

const semanticGenres=new Map(taxonomy.genres.flatMap(row=>[row.key,row.label,...row.aliases].map(label=>[String(label).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim(),row])));
export const normalizeTag=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
export function discoveredTagIdentity(value){
 let text=readableCatalogLabel(value).replace(/\s*[([{]\s*\d{1,9}\s*[)\]}]\s*$/u,'');
 if((text.match(/\p{L}/gu)||[]).length>=3)text=text.replace(/(?:\s+|[-_/|:]+)\d{1,9}\s*$/u,'');
 return normalizeTag(text);
}
export function compileMangaPolicy(data){
 if(data?.schemaVersion!==1||!Array.isArray(data.tags)||!Array.isArray(data.excludedTerms)||!Array.isArray(data.excludedPrefixes))throw Error('Неверный формат правил тегов.');
 if(data.includeDiscovered!=null&&typeof data.includeDiscovered!=='boolean'||data.hiddenTags!=null&&!Array.isArray(data.hiddenTags))throw Error('Неверный режим справочника.');
 const rawRules=new Map(),aliases=new Map(),scoped=new Map(),hidden=new Set(),redirects=new Map();
 const terms=data.excludedTerms.map(normalizeTag),prefixes=data.excludedPrefixes.map(normalizeTag);
 const clean=value=>typeof value==='string'&&value.trim().length>=1&&value.length<=120&&!terms.some(t=>(' '+normalizeTag(value)+' ').includes(' '+t+' '))&&!normalizeTag(value).split(' ').some(w=>prefixes.some(p=>w.startsWith(p)));
 for(const row of data.tags){
  const valid=value=>typeof value==='string'&&value.trim().length>=1&&value.length<=120;
  if(!row.key||normalizeTag(row.key)!==row.key||rawRules.has(row.key)||!valid(row.label)||!Array.isArray(row.aliases))throw Error('Неверная запись тега.');
  if(row.category!=null&&!['tag','genre'].includes(row.category))throw Error('Выбери категорию: тег или жанр.');
  const display={...row,label:readableCatalogLabel(row.label),aliases:[...new Set(row.aliases.flatMap(value=>[value,readableCatalogLabel(value)]).filter(Boolean))]};
  rawRules.set(row.key,display);
  for(const value of [row.key,row.label,...display.aliases]){const alias=normalizeTag(value);if(!valid(value)||aliases.has(alias)&&aliases.get(alias)!==row.key)throw Error('Неоднозначный алиас тега.');aliases.set(alias,row.key);if(!clean(value))hidden.add(row.key);}
  for(const [domain,values] of Object.entries(row.sourceAliases||{}))for(const value of values){const alias=domain+':'+normalizeTag(value);if(!valid(value)||scoped.has(alias)&&scoped.get(alias)!==row.key)throw Error('Неоднозначный алиас источника.');scoped.set(alias,row.key);if(!clean(value))hidden.add(row.key);}
 }
 const resolve=value=>{const seen=new Set();while(redirects.has(value)&&!seen.has(value)){seen.add(value);value=redirects.get(value);}return value;};
 const group=(row,category)=>{
  const values=[row.key,row.label,...(row.aliases||[])],candidates=[...new Set(values.map(value=>aliases.get(normalizeTag(value))).filter(Boolean).map(resolve))];
  const id=resolve(aliases.get(normalizeTag(row.key))||candidates[0]||normalizeTag(row.label));
  if(!rawRules.has(id)&&!data.includeDiscovered)return;
  if(!rawRules.has(id))rawRules.set(id,{key:id,label:row.label,aliases:[],category});
  for(const candidate of candidates)if(candidate!==id)redirects.set(candidate,id);
  const known=new Set(values.map(normalizeTag)),base={...rawRules.get(id)},current=readableCatalogLabel(base.label);
  base.key=id;base.label=known.has(normalizeTag(current))?row.label:current||row.label;base.category=base.category||category;
  base.aliases=[...new Set([...(base.aliases||[]),...values])].slice(0,120);rawRules.set(id,base);
  for(const value of values)aliases.set(normalizeTag(value),id);
 };
 for(const genre of taxonomy.genres)group(genre,'genre');
 for(const row of taxonomy.tagGroups||[])group(row,row.category||'tag');
 for(const [alias,id] of aliases)aliases.set(alias,resolve(id));
 for(const [alias,id] of scoped)scoped.set(alias,resolve(id));
 const rules=new Map();
 for(const [old,row] of rawRules){
  const id=resolve(old),canonical=rawRules.get(id)||row,target=rules.get(id)||{key:id,label:readableCatalogLabel(canonical.label)||id,aliases:[],...(canonical.category?{category:canonical.category}:{})};
  // Provider spellings precede internal canonical keys because upstream
  // query adapters intentionally choose the first usable Latin alias.
  target.aliases=[...new Set([...target.aliases,readableCatalogLabel(row.label),...(row.aliases||[]),old].filter(Boolean))].slice(0,120);
  if(row.category&&!target.category)target.category=row.category;
  const sourceAliases={...(target.sourceAliases||{})};
  for(const [domain,values] of Object.entries(row.sourceAliases||{}))sourceAliases[domain]=[...new Set([...(sourceAliases[domain]||[]),...values])];
  if(Object.keys(sourceAliases).length)target.sourceAliases=sourceAliases;
  rules.set(id,target);
 }
 for(const value of data.hiddenTags||[])hidden.add(resolve(aliases.get(normalizeTag(value))||discoveredTagIdentity(value)));
 const key=(value,source='')=>{const norm=normalizeTag(value),fallback=discoveredTagIdentity(value),id=clean(value)&&!hidden.has(norm)?scoped.get(source+':'+norm)||aliases.get(norm)||aliases.get(fallback)||(data.includeDiscovered?fallback:''):'';return hidden.has(id)?'':id;};
 const label=(id,fallback='')=>rules.get(id)?.label||fallback||id;
 const project=(values,source='')=>{const found=new Map();for(const value of Array.isArray(values)?values:[]){const id=key(value,source);if(id)found.set(id,label(id,value));}return [...found.values()];};
 const facts=(row,source='')=>{const result={genres:[],tags:[]},kind=row?.kind||'manga';for(const field of ['genres','tags'])for(const raw of Array.isArray(row?.[field])?row[field]:[]){const value=readableCatalogLabel(raw),id=key(value,source);if(!id||/^\p{N}+$/u.test(value))continue;const rule=rules.get(id)||{},genre=[value,rule.key,rule.label,...(rule.aliases||[])].map(v=>semanticGenres.get(normalizeTag(v))).find(Boolean),target=({genre:'genres',tag:'tags'})[rule.category]||(genre?'genres':'tags');if(genre?.kinds&&!genre.kinds.includes(kind)||kind==='book'&&(target!=='genres'||!genre&&rule.category!=='genre'))continue;const name=rule.label||(genre&&target==='genres'?genre.label:value);if(!result[target].includes(name))result[target].push(name);}const hentai=key('Хентай',source);return sourceGenreProjection(row,result,{source,allowed:!!hentai&&rules.get(hentai)?.category!=='tag',label:label(hentai,'Хентай'),isHentai:value=>hentaiLabel(value)||!!hentai&&key(value,source)===hentai});};
 return {data,rules,key,label,project,facts};
}
let active=compileMangaPolicy(bundled),version=0,scope='manga';
const listeners=new Set();
export const mangaPolicy=()=>active;
export const policyVersion=()=>version;
export const subscribeMangaPolicy=listener=>{listeners.add(listener);return()=>listeners.delete(listener);};
let revision='';
export const contentPolicyRevision=()=>revision;
export function setMangaPolicy(data,digest='',nextScope='manga'){
 if(digest&&digest===revision&&nextScope===scope)return;
 const next=compileMangaPolicy(data);active=next;revision=digest;scope=nextScope;version++;for(const listener of listeners)listener();
}
export function acceptContentPolicy(value){const next=value?.tagPolicy;if(next?.policy)setMangaPolicy(next.policy,next.revision,next.scope||'all');return value;}
export function mangaPolicyFacts(row){
 let source='';try{source=new URL(row.sourceUrl||row.url||'').hostname;}catch{}
 return {...row,...active.facts(row,source),...(hentaiExcluded(row)?{hentaiExcluded:true}:{})};
}
export function mangaPolicyProfile(profile,kind=profile?.kind||'manga'){const facts=active.facts({...profile,kind,genres:profile?.genres,tags:profile?.themes});return {...profile,genres:facts.genres,themes:facts.tags};}
export const globalContentPolicy=()=>scope==='all';
export const contentPolicyFacts=row=>row.kind==='manga'||globalContentPolicy()?mangaPolicyFacts(row):row;
