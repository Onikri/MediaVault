import data from '../server/catalog-taxonomy.json' with {type:'json'};
import {mangaPolicy} from './manga-tag-policy.js';
import {hentaiExcluded,hentaiLabel,sourceGenreProjection} from './source-genres.js';
import {readableCatalogLabel,readableCatalogLabels} from './catalog-label.js';
const norm=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/[_-]/g,' ').replace(/\s+/g,' ').trim();
const genres=new Map(data.genres.flatMap(row=>[row.key,row.label,...row.aliases].map(alias=>[norm(alias),row])));
export function filterValues(value){if(Array.isArray(value))return value;try{if(String(value||'').startsWith('['))return JSON.parse(value);}catch{}return String(value||'').split(',').map(v=>v.trim()).filter(Boolean);}
export const filterParam=value=>Array.isArray(value)?JSON.stringify(value):value??'';
export const hasCatalogFilters=filters=>['genre','tag','excludeGenre','excludeTag'].some(key=>filterValues(filters[key]).length>0)||['format','readingMode','year','age','status'].some(key=>!!filters[key]);
function semanticGenre(label,policy=mangaPolicy()){
 const value=readableCatalogLabel(label),rule=policy.rules.get(policy.key(value));
 return [value,rule?.label,rule?.key,...(rule?.aliases||[])].map(candidate=>genres.get(norm(candidate))).find(Boolean);
}
export function classifyLabel(label,field,kind){
 if(!label||/^\p{N}+$/u.test(String(label).trim()))return null;
 label=readableCatalogLabel(label);
 const policy=mangaPolicy(),rule=policy.rules.get(policy.key(label)),genre=semanticGenre(label,policy);
 const category=({genre:'genres',tag:'tags'})[rule?.category]||(genre?'genres':'tags');
 if(kind==='book'&&(category!=='genres'||!genre&&rule?.category!=='genre'))return null;
 if(genre?.kinds&&!genre.kinds.includes(kind))return null;
 return {category,label:rule?.label||(genre&&category==='genres'?genre.label:label)};
}
export function taxonomyFacts(row){
 const result={genres:[],tags:[]};
 for(const field of ['genres','tags'])for(const label of [...row[field]||[],...row.workFacts?.[field]||[]]){const value=classifyLabel(label,field,row.kind);if(value&&!result[value.category].includes(value.label))result[value.category].push(value.label);}
 const policy=mangaPolicy(),id=policy.key('Хентай');
 const projected=sourceGenreProjection(row,result,{allowed:!!id&&policy.rules.get(id)?.category!=='tag',label:policy.label(id,'Хентай'),isHentai:v=>hentaiLabel(v)||!!id&&policy.key(v)===id});
 return {...row,...projected,...(hentaiExcluded(row)?{hentaiExcluded:true}:{}),format:formatLabel(row.format,row.kind)};
}
export const genreOptions=kind=>data.genres.filter(row=>!row.kinds||row.kinds.includes(kind)).map(row=>row.label);
export const formatOptions=kind=>data.formats[kind]||[];
export {readableCatalogLabel,readableCatalogLabels};
export function matchesTaxonomy(row,filters){
 const facts=taxonomyFacts(row),key=value=>norm(genres.get(norm(value))?.label||mangaPolicy().label(mangaPolicy().key(value),value));
 for(const [field,name,negative] of [['genres','genre',false],['tags','tag',false],['genres','excludeGenre',true],['tags','excludeTag',true]]){
  const selected=filterValues(filters[name]);if(!selected.length)continue;
  const found=selected.some(value=>facts[field].some(label=>key(label)===key(value)));
  if(negative?found:!found)return false;
 }
 return true;
}

export const formatLabel=(value,kind)=>data.formatAliases?.[kind]?.[String(value||'').toLocaleLowerCase()]||value;
