// Danbooru's public JSON API answers browsers directly (CORS *), so art is
// fetched on demand without our server or a cache. Only general-rated posts.
// Its CDN refuses images requested without a Referer, so pins send our origin.
const BASE='https://danbooru.donmai.us';
const KIND={4:'character',3:'copyright'};
const label=name=>name.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());

// A typed name, or a character's romanised name, becomes Danbooru tags:
// characters first, then series, the most drawn first.
export async function findArtTags(text,{signal,hint=''}={}){
 const query=String(text).trim().toLowerCase().replace(/\s+/g,' ');
 if(!query)return [];
 const url=BASE+'/autocomplete.json?'+new URLSearchParams({'search[query]':query,'search[type]':'tag_query',limit:'12'});
 const response=await fetch(url,{signal,credentials:'omit',referrerPolicy:'no-referrer'});
 if(!response.ok)throw Error('art tags '+response.status);
 const rows=await response.json();
 const hintWords=String(hint).toLowerCase().split(/[^a-z0-9]+/).filter(w=>w.length>2);
 return (Array.isArray(rows)?rows:[])
  .filter(row=>KIND[row.category]&&row.post_count>0)
  .map(row=>({name:row.value,label:label(row.value.replace(/_\([^)]*\)$/,'')),kind:KIND[row.category],count:row.post_count,hinted:hintWords.some(w=>row.value.includes(w))}))
  .sort((a,b)=>(b.kind==='character')-(a.kind==='character')||(b.hinted-a.hinted)||b.count-a.count)
  .slice(0,8);
}

export async function loadArts(tag,page=1,{signal}={}){
 const url=BASE+'/posts.json?'+new URLSearchParams({tags:tag+' rating:g',limit:'30',page:String(page)});
 const response=await fetch(url,{signal,credentials:'omit',referrerPolicy:'no-referrer'});
 if(!response.ok)throw Error('arts '+response.status);
 const rows=await response.json();
 return (Array.isArray(rows)?rows:[]).filter(post=>post.rating==='g'&&!post.is_banned&&!post.is_deleted&&post.image_width&&post.image_height).map(post=>{
  const variants=post.media_asset?.variants||[],pick=type=>variants.find(v=>v.type===type)?.url;
  const preview=pick('360x360')||pick('720x720')||post.preview_file_url,large=pick('sample')||post.large_file_url||post.file_url;
  return preview&&large?{id:post.id,width:post.image_width,height:post.image_height,preview,large,artist:label(String(post.tag_string_artist||'').split(' ')[0]||''),page:BASE+'/posts/'+post.id}:null;
 }).filter(Boolean);
}
