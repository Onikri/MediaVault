const normalize=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
const aliases=item=>(item.identityTitles?.length?item.identityTitles:[item.title,item.originalTitle,item.original_title,...Object.values(item.titles||{}),...item.aliases||[]]).filter(v=>typeof v==='string').flatMap(v=>v.split(/\s\/\s|\s\|\s/)).map(normalize).filter(v=>v.length>1);

// A provider search result is a candidate, not evidence that it belongs to this title.
export function sameMangaTitle(selected,candidate){
 if(selected.kind&&candidate.kind&&selected.kind!==candidate.kind)return false;
 const shared=Object.keys(selected.ids||{}).filter(key=>selected.ids[key]&&candidate.ids?.[key]);
 if(shared.some(key=>String(selected.ids[key])!==String(candidate.ids[key])))return false;
 if(shared.length)return true;
 if(selected.year&&candidate.year&&String(selected.year).slice(0,4)!==String(candidate.year).slice(0,4))return false;
 const expected=new Set(aliases(selected));
 return aliases(candidate).some(value=>expected.has(value));
}

export function matchingMangaSources(item,rows,{attached=false}={}){
 if(!item)return [];
 return [...new Map(rows.filter(row=>row.url&&(attached&&!row.title||sameMangaTitle(item,row))).map(row=>[row.url,{...row,title:row.title||item.title}])).values()].sort((a,b)=>Number(b.provider==='mangalib')-Number(a.provider==='mangalib'));
}
