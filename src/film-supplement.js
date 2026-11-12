// Films and series: the Kinopoisk record (Kinobox) has a poster, genres and
// a score only. Two free public catalogs, both open to the browser (CORS) and
// keyless, fill the page the way Shikimori fills an anime:
//  · Wikidata, found by the Kinopoisk or IMDb ID: cast with roles and photos,
//    directors, writers, composers, studios, countries, runtime, seasons,
//    episodes, the franchise (series, previous and next work);
//  · TVmaze, found by the IMDb ID (series only): characters with images,
//    episode stills and air dates, seasons, network and airing status.
// Only exact ID matches are used; nothing is guessed from a title.

const WIKIDATA='https://www.wikidata.org/w/api.php';
const timed=(signal,ms=12000)=>AbortSignal.any([signal,AbortSignal.timeout(ms)].filter(Boolean));
async function json(url,signal){
 const response=await fetch(url,{signal:timed(signal),referrerPolicy:'no-referrer'});
 if(!response.ok)throw Error('Каталог ответил '+response.status);
 return response.json();
}
const wikidata=(params,signal)=>json(WIKIDATA+'?'+new URLSearchParams({format:'json',origin:'*',...params}),signal);
const ids=(claims,property)=>(claims?.[property]||[]).filter(c=>c.rank!=='deprecated').map(c=>c.mainsnak?.datavalue?.value?.id).filter(Boolean);
const value=(claims,property)=>(claims?.[property]||[]).find(c=>c.rank!=='deprecated')?.mainsnak?.datavalue?.value;
const commons=(file,width=360)=>file?'https://commons.wikimedia.org/wiki/Special:FilePath/'+encodeURIComponent(String(file).replace(/ /g,'_'))+'?width='+width:'';
const label=entity=>entity?.labels?.ru?.value||entity?.labels?.en?.value||'';
const day=time=>{const match=/^\+?(\d{4})-(\d{2})-(\d{2})/.exec(time||'');return match?match[1]+'-'+(match[2]==='00'?'01':match[2])+'-'+(match[3]==='00'?'01':match[3]):'';};
const clean=text=>String(text||'').replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim();

async function entities(list,signal,props='labels|claims'){
 const unique=[...new Set(list)].filter(id=>/^Q\d+$/.test(id)),rows={};
 for(let i=0;i<unique.length;i+=50){
  const data=await wikidata({action:'wbgetentities',ids:unique.slice(i,i+50).join('|'),props,languages:'ru|en'},signal);
  Object.assign(rows,data.entities||{});
 }
 return rows;
}
async function wikidataEntity(item,signal){
 const statements=[item.ids?.kinopoisk&&'haswbstatement:P2603='+item.ids.kinopoisk,item.ids?.imdb&&'haswbstatement:P345='+item.ids.imdb].filter(Boolean);
 for(const query of statements){
  const found=await wikidata({action:'query',list:'search',srsearch:query,srlimit:'2'},signal);
  const id=found.query?.search?.[0]?.title;
  if(id)return (await entities([id],signal,'labels|claims|sitelinks'))[id]||null;
 }
 return null;
}
const minutes=claims=>{
 const amount=value(claims,'P2047');if(!amount)return null;
 const number=Math.abs(Number(amount.amount)),unit=String(amount.unit||'');
 return Math.round(unit.endsWith('Q7727')?number:unit.endsWith('Q11574')?number/60:unit.endsWith('Q25235')?number*60:number)||null;
};

async function fromWikidata(item,signal){
 const entity=await wikidataEntity(item,signal);if(!entity)return {};
 const c=entity.claims||{};
 const cast=(c.P161||[]).filter(s=>s.rank!=='deprecated'&&s.mainsnak?.datavalue).slice(0,24).map(s=>({actor:s.mainsnak.datavalue.value.id,roles:(s.qualifiers?.P453||[]).map(q=>q.datavalue?.value?.id).filter(Boolean),names:(s.qualifiers?.P4633||[]).map(q=>q.datavalue?.value).filter(Boolean)}));
 const people={directors:ids(c,'P57'),writers:ids(c,'P58'),composers:ids(c,'P86'),producers:ids(c,'P162').slice(0,4),operators:ids(c,'P344').slice(0,2),creators:ids(c,'P170')};
 const family={series:ids(c,'P179'),previous:ids(c,'P155'),next:ids(c,'P156'),basedOn:ids(c,'P144')};
 const lookup=await entities([...cast.flatMap(r=>[r.actor,...r.roles]),...Object.values(people).flat(),...Object.values(family).flat(),...ids(c,'P272'),...ids(c,'P495'),...ids(c,'P449')],signal);
 const person=(id,role)=>lookup[id]&&{id:'wd:'+id,name:label(lookup[id]),role,image:commons(value(lookup[id].claims,'P18'))};
 const staff=[
  ...people.creators.map(id=>person(id,'Создатель')),...people.directors.map(id=>person(id,'Режиссёр')),...people.writers.map(id=>person(id,'Сценарий')),
  ...people.composers.map(id=>person(id,'Композитор')),...people.operators.map(id=>person(id,'Оператор')),...people.producers.map(id=>person(id,'Продюсер'))
 ].filter(p=>p?.name).reduce((list,p)=>{const same=list.find(v=>v.id===p.id);if(same)same.role+=', '+p.role.toLocaleLowerCase('ru');else list.push({...p});return list;},[]);
 const characters=cast.map(row=>{
  const actor=lookup[row.actor];if(!actor)return null;
  const role=row.roles.map(id=>label(lookup[id])).find(Boolean)||row.names[0]||'';
  const image=commons(value(actor.claims,'P18'));
  return {id:'wd:'+row.actor,name:role||label(actor),role:role?label(actor):'В ролях',image,actors:role?[label(actor)]:[],description:''};
 }).filter(Boolean);
 const related=[...family.previous.map(id=>[id,'Предыдущая часть']),...family.next.map(id=>[id,'Следующая часть']),...family.basedOn.map(id=>[id,'Первоисточник'])]
  .filter(([id])=>lookup[id]).map(([id,relation])=>({id:'wd:'+id,kind:'wikidata',title:label(lookup[id]),relation,format:'',cover:commons(value(lookup[id].claims,'P18'),300),wikidata:id}));
 const seasons=Number(value(c,'P2437')?.amount)||null,episodes=Number(value(c,'P1113')?.amount)||null;
 return {
  imdb:value(c,'P345')||'',duration:minutes(c),countries:ids(c,'P495').map(id=>label(lookup[id])).filter(Boolean),
  studios:ids(c,'P272').map(id=>label(lookup[id])).filter(Boolean).slice(0,4),network:ids(c,'P449').map(id=>label(lookup[id])).find(Boolean)||'',
  directors:people.directors.map(id=>label(lookup[id])).filter(Boolean),staff,characters,related,
  franchise:family.series.map(id=>label(lookup[id])).find(Boolean)||'',
  seasons:seasons?Math.abs(seasons):null,episodes:episodes?Math.abs(episodes):null,
  startDate:day(value(c,'P580')?.time||value(c,'P577')?.time),endDate:day(value(c,'P582')?.time),
  wikipedia:entity.sitelinks?.ruwiki?.title?'https://ru.wikipedia.org/wiki/'+encodeURIComponent(entity.sitelinks.ruwiki.title.replace(/ /g,'_')):'',
 };
}

const TVMAZE_STATUS={Running:['Выходит','ongoing'],Ended:['Завершён','released'],'To Be Determined':['Продление не объявлено','ongoing'],'In Development':['Анонс','anons']};
async function fromTvmaze(imdb,signal){
 if(!/^tt\d+$/.test(imdb||''))return {};
 const show=await json('https://api.tvmaze.com/lookup/shows?imdb='+imdb,signal).catch(()=>null);if(!show?.id)return {};
 const [full,images]=await Promise.all([
  json('https://api.tvmaze.com/shows/'+show.id+'?embed[]=cast&embed[]=episodes&embed[]=seasons',signal),
  json('https://api.tvmaze.com/shows/'+show.id+'/images',signal).catch(()=>[]),
 ]);
 const episodes=(full._embedded?.episodes||[]).filter(e=>e.type!=='insignificant_special');
 const now=Date.now(),aired=episodes.filter(e=>e.airstamp&&Date.parse(e.airstamp)<=now);
 const seasons=(full._embedded?.seasons||[]).filter(s=>s.number>0);
 const [status,statusCode]=TVMAZE_STATUS[full.status]||[];
 const picture=row=>row?.image?.original||row?.image?.medium||'';
 return {
  tvmaze:String(show.id),status,statusCode,
  seasons:seasons.length||null,episodes:episodes.length||null,episodesAired:aired.length||null,
  seasonList:seasons.map(s=>({number:s.number,episodes:s.episodeOrder||episodes.filter(e=>e.season===s.number).length||null,start:s.premiereDate||'',end:s.endDate||'',image:picture(s)})),
  duration:full.averageRuntime||full.runtime||null,network:full.network?.name||full.webChannel?.name||'',
  schedule:full.schedule?.days?.length?full.schedule:null,
  characters:(full._embedded?.cast||[]).slice(0,24).map(row=>({id:'tvmaze:'+row.character.id,name:row.character.name,role:row.person.name,image:picture(row.character)||picture(row.person),actors:[row.person.name],description:''})),
  screenshots:(images||[]).filter(i=>i.type==='background').map(i=>i.resolutions?.original?.url).filter(Boolean).slice(0,10),
  backgrounds:(images||[]).filter(i=>i.type==='background').map(i=>i.resolutions?.original?.url).filter(Boolean).slice(0,4),
  episodeImages:Object.fromEntries(episodes.filter(picture).map(e=>[e.season+':'+e.number,e.image.medium||e.image.original])),
  episodeTitles:Object.fromEntries(episodes.map(e=>[e.season+':'+e.number,clean(e.name)])),
  releases:episodes.filter(e=>e.airstamp).map(e=>({episode:e.number,season:e.season,date:e.airstamp,kind:'original',provider:'tvmaze'})),
  endDate:full.ended||'',tvmazeURL:full.url||'',
 };
}

// A movie or series profile filled from both catalogs. Values from the
// Kinopoisk record stay first; the catalogs only add what is missing.
export async function filmSupplement(item,{signal}={}){
 if(!['movie','tv'].includes(item?.kind))return {};
 const wiki=await fromWikidata(item,signal).catch(()=>({}));
 const imdb=item.ids?.imdb||wiki.imdb;
 const show=item.kind==='tv'?await fromTvmaze(imdb,signal).catch(()=>({})):{};
 // TVmaze names the characters with their pictures; Wikidata has the actor
 // photos. A series takes TVmaze's cast when it has one.
 const characters=show.characters?.length?show.characters:wiki.characters||[];
 return {...wiki,...Object.fromEntries(Object.entries(show).filter(([,v])=>v!=null&&v!==''&&!(Array.isArray(v)&&!v.length))),characters,imdb:imdb||'',
  seasons:show.seasons||wiki.seasons||null,episodes:show.episodes||wiki.episodes||null};
}
