// Exact external identifiers only: no guessed sequels or name-only game matches.
const ids=(entity,property)=>(entity.claims?.[property]||[]).map(c=>c.mainsnak?.datavalue?.value?.id).filter(id=>/^Q\d+$/.test(id));
const first=(entity,property)=>entity.claims?.[property]?.[0]?.mainsnak?.datavalue?.value;
async function json(url,options={}){const response=await fetch(url,{...options,signal:AbortSignal.timeout(8000),credentials:'omit'});if(!response.ok)throw Error('Каталог связей сейчас недоступен.');return response.json();}
async function entities(values){
  if(!values.length)return {};
  const data=await json('https://www.wikidata.org/w/api.php?'+new URLSearchParams({action:'wbgetentities',ids:[...new Set(values)].slice(0,50).join('|'),props:'labels|descriptions|claims',languages:'ru',format:'json',origin:'*'}));
  return data.entities||{};
}
export function wikidataRelations(entity,values,types={}){
  const relations=new Map();
  for(const [property,label] of [['P144','Первоисточник'],['P4969','По мотивам'],['P179','Цикл']])for(const id of ids(entity,property))relations.set(id,label);
  for(const value of Object.values(values))if(ids(value,'P144').includes(entity.id))relations.set(value.id,'По мотивам');
  return [...relations].map(([id,relation])=>{
    const value=values[id];if(!value?.labels?.ru?.value)return null;
    const typeIds=ids(value,'P31'),type=typeIds.map(id=>types[id]?.labels?.ru?.value||'').join(' ').toLowerCase();
    const kind=typeIds.includes('Q7889')||/видеоигр|компьютерн.*игр|визуальн.*новелл/.test(type)?'game':/ранобэ/.test(type)?'ranobe':/манга|манхва|маньхуа/.test(type)?'manga':typeIds.includes('Q11424')||/фильм/.test(type)?'movie':/аниме|телесериал/.test(type)?'anime':typeIds.some(id=>['Q571','Q8261'].includes(id))||/роман|книга|повесть|литератур/.test(type)?'book':null;
    if(!kind)return null;
    const filename=first(value,'P18'),release=first(value,'P577')?.time,site=first(value,'P856'),steam=first(value,'P1733');
    const sourceURL='https://www.wikidata.org/wiki/'+id;
    return {id,provider:'wikidata',kind:first(value,'P4086')?'anime':kind,ids:{...(first(value,['manga','ranobe'].includes(kind)?'P4087':'P4086')?{mal:String(first(value,['manga','ranobe'].includes(kind)?'P4087':'P4086'))}:{})},title:value.labels.ru.value,description:value.descriptions?.ru?.value||'',relation,
      format:{game:'Игра',book:'Книга',ranobe:'Ранобэ',manga:'Манга',movie:'Фильм',anime:'Аниме'}[kind],
      year:release?Number(release.match(/\d{4}/)?.[0])||null:null,
      cover:typeof filename==='string'?'https://commons.wikimedia.org/wiki/Special:FilePath/'+encodeURIComponent(filename)+'?width=800':'',
      sourceURL,externalURL:typeof site==='string'&&site.startsWith('https://')?site:/^\d+$/.test(String(steam||''))?'https://store.steampowered.com/app/'+steam:sourceURL};
  }).filter(Boolean);
}
export async function crossMediaFromLinks(links){
  const wiki=links.map(link=>link.url).filter(Boolean).map(value=>{try{return new URL(value.replace(/^http:/,'https:'));}catch{return null;}}).find(url=>url&&/^(?:[a-z-]+\.)?wikipedia\.org$/.test(url.hostname)&&url.pathname.startsWith('/wiki/'));
  if(!wiki)return [];
  const page=decodeURIComponent(wiki.pathname.slice(6));
  const result=await json(wiki.origin+'/w/api.php?'+new URLSearchParams({action:'query',prop:'pageprops',ppprop:'wikibase_item',titles:page,redirects:'1',format:'json',origin:'*'}));
  const identity=Object.values(result.query?.pages||{}).map(p=>p.pageprops?.wikibase_item).find(Boolean);if(!identity)return [];
  const main=(await entities([identity]))[identity];if(!main)return [];
  const baseIds=[...ids(main,'P144'),...ids(main,'P4969'),...ids(main,'P179')].filter(id=>id!==identity).slice(0,16);
  const base=await entities(baseIds);
  // One hop through a confirmed source work includes adaptations and games.
  const derivatives=ids(main,'P144').flatMap(id=>base[id]?ids(base[id],'P4969'):[]).filter(id=>id!==identity).slice(0,16);
  const values={...base,...await entities(derivatives)};
  const types=await entities(Object.values(values).flatMap(value=>ids(value,'P31')));
  const extended={...main,claims:{...main.claims,P4969:[...(main.claims?.P4969||[]),...derivatives.map(id=>({mainsnak:{datavalue:{value:{id}}}}))]}};
  return wikidataRelations(extended,values,types);
}
export async function highResolutionArtwork(id,kind){
  const data=await json('https://graphql.anilist.co',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:'query($id:Int,$type:MediaType){Media(idMal:$id,type:$type){id idMal bannerImage coverImage{extraLarge} siteUrl}}',variables:{id:Number(id),type:kind==='anime'?'ANIME':'MANGA'}})});
  const media=data.data?.Media;if(Number(media?.idMal)!==Number(id))return null;
  return {background:media.bannerImage||'',cover:media.coverImage?.extraLarge||'',sourceURL:media.siteUrl};
}
