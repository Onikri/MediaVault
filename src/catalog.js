import {localLabel,queryLabel} from './taxonomy.js';
import {mangaPolicy,globalContentPolicy} from './manga-tag-policy.js';
import {russianText,translate,imageURL} from './title-metadata.js';
import {contentLanguage} from './content-language.js';
import {uiLanguage} from './i18n/index.js';
// Free metadata only. Source discovery and every media byte stay on the import server.
const strip=value=>String(value||'').replace(/<[^>]*>/g,' ').replace(/\[\/?(?:b|i|u|url|spoiler|quote)[^\]]*\]/g,' ').replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/\s+/g,' ').trim();
export const normalized=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
// A spelling fallback, not a translation: e.g. Наруто → naruto. Keep the
// original query and metadata intact; translated titles still need catalogue aliases.
const cyrillic={а:'a',б:'b',в:'v',г:'g',д:'d',е:'e',ё:'yo',ж:'zh',з:'z',и:'i',й:'y',к:'k',л:'l',м:'m',н:'n',о:'o',п:'p',р:'r',с:'s',т:'t',у:'u',ф:'f',х:'h',ц:'ts',ч:'ch',ш:'sh',щ:'shch',ъ:'',ы:'y',ь:'',э:'e',ю:'yu',я:'ya',і:'i',ї:'yi',є:'ye',ґ:'g'};
export function alternateSpelling(query){
  const value=String(query||'').normalize('NFKC').trim();
  return value.length>=2&&/[а-яёіїєґ]/i.test(value)?value.toLocaleLowerCase().replace(/[а-яёіїєґ]/g,char=>cyrillic[char]):'';
}
export function rankCatalog(items,query){
  const terms=[query,alternateSpelling(query)].map(normalized).filter(Boolean);
  if(!terms.length)return items;
  const score=item=>Math.max(0,...item.aliases.flatMap(alias=>terms.map(term=>{
    const value=normalized(alias);
    return value===term?1000:value.startsWith(term+' ')?800:value.startsWith(term)?700:value.includes(term)?500:term.split(' ').every(word=>value.includes(word))?300:0;
  })));
  return items.map((item,index)=>({item,index,score:score(item)})).sort((a,b)=>b.score-a.score||a.index-b.index).map(value=>value.item);
}
export const safeImage=value=>{try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:'';}catch{return '';}};
const yearOf=value=>value?Number(String(value).slice(0,4))||null:null;
const fuzzyDate=value=>!value?.year?null:[value.year,...(value.month?[String(value.month).padStart(2,'0')]:[]),...(value.month&&value.day?[String(value.day).padStart(2,'0')]:[])].join('-');
const unique=values=>[...new Set(values.filter(Boolean))];
export const genreLabels={Action:'Экшен',Adventure:'Приключения',Comedy:'Комедия',Drama:'Драма',Fantasy:'Фэнтези',Horror:'Ужасы',Mystery:'Детектив',Romance:'Романтика','Sci-Fi':'Фантастика','Science Fiction':'Фантастика','Slice of Life':'Повседневность',Sports:'Спорт',Supernatural:'Сверхъестественное',Suspense:'Триллер',Thriller:'Триллер',Mecha:'Меха',Music:'Музыка',Psychological:'Психология',Historical:'История',School:'Школа'};
export const providers={kitsu:'Kitsu',anilist:'AniList',shikimori:'Shikimori',jikan:'MyAnimeList / Jikan',kinobox:'Кинопоиск · Kinobox',openlibrary:'Open Library',fantlab:'Fantlab',imdb:'IMDb',tvmaze:'TVmaze',wikidata:'Wikidata'};
const ageOf=value=>/^(R18|rx|r_plus)|18\+|NC-17/i.test(value||'')?18:/^R\b|R - 17|17\+/i.test(value||'')?17:/^PG[-_]13|13\+/i.test(value||'')?13:/^PG\b/i.test(value||'')?12:/^G\b/i.test(value||'')?0:null;
export const validExternalIds=values=>Object.fromEntries(Object.entries(values||{}).filter(([key,value])=>['mal','anilist','kitsu','shikimori'].includes(key)?/^[1-9]\d{0,11}$/.test(String(value)):key==='imdb'?/^tt[1-9]\d{0,11}$/.test(String(value)):typeof value==='string'&&!!value));
const dates=values=>(values||[]).map(x=>({...x,date:typeof x.date==='number'?new Date(x.date*1000).toISOString():x.date})).filter(x=>x.date&&!Number.isNaN(Date.parse(x.date)));
function record(provider,id,kind,values){
  if(['manga','ranobe'].includes(kind))kind=/novel|раноб[эе]/i.test(values.format||'')?'ranobe':'manga';
  const titles=values.titles||{};
  const title=strip(titles.ru||titles.uk||titles.en||values.title||titles.native||'Без названия');
  return {...values,id:provider+':'+id,provider,providerId:String(id),providers:[provider],kind,title,
    titles,aliases:unique([title,...Object.values(titles),...(values.aliases||[])]),description:russianText(values.description),
    cover:safeImage(values.cover),year:values.year||yearOf(values.startDate),format:kind==='anime'?translate(values.format,'Аниме'):kind==='ranobe'?(/^novel$/.test(values.format||'')?'Новелла':'Ранобэ'):values.format||'',
    genres:unique(values.genres||[]),tags:unique(values.tags||[]),age:values.age??null,ageLabel:values.ageLabel||'',
    episodes:values.episodes||null,chapters:values.chapters||null,volumes:values.volumes||null,
    status:values.status||'',startDate:values.startDate||null,endDate:values.endDate||null,
    releases:dates(values.releases),ids:validExternalIds(values.ids),links:values.links||[]};
}
export function normalizeCatalog(provider,data,kind='anime'){
  const list=value=>Array.isArray(value)?value:value?[value]:[];
  if(provider==='kitsu'){
    const included=new Map((data.included||[]).map(item=>[item.type+':'+item.id,item]));
    return list(data.data).map(item=>{
      const a=item.attributes||{},related=key=>(item.relationships?.[key]?.data||[]).map(ref=>included.get(ref.type+':'+ref.id)).filter(Boolean);
      const genres=related('genres').map(x=>x.attributes?.name),categories=related('categories').map(x=>x.attributes?.title);
      const mapping=related('mappings').find(x=>/myanimelist/.test(x.attributes?.externalSite));
      return record(provider,item.id,kind,{titles:{en:a.titles?.en||a.titles?.en_us,ru:a.titles?.ru_ru,native:a.titles?.ja_jp||a.titles?.zh_cn||a.titles?.ko_kr},title:a.canonicalTitle,aliases:[...Object.values(a.titles||{}),...(a.abbreviatedTitles||[])],description:a.synopsis,
        cover:a.posterImage?.large||a.posterImage?.medium,format:a.subtype,year:yearOf(a.startDate),startDate:a.startDate,endDate:a.endDate,
        genres,tags:categories,age:ageOf(a.ageRating),ageLabel:a.ageRatingGuide||a.ageRating,episodes:a.episodeCount,chapters:a.chapterCount,volumes:a.volumeCount,status:a.status,
        ids:mapping?{mal:String(mapping.attributes.externalId)}:{},links:[{provider,url:'https://kitsu.io/'+(item.type==='manga'?'manga':'anime')+'/'+(a.slug||item.id)}]});
    });
  }
  if(provider==='anilist')return list(data.data?.Media||data.data?.Page?.media).map(a=>record(provider,a.id,kind,{
    titles:{ru:a.russian,en:a.title?.english,native:a.title?.native},title:a.title?.romaji,aliases:[a.title?.romaji,...(a.synonyms||[])],description:a.description,cover:a.coverImage?.large,
    score:Number(a.averageScore)?Number(a.averageScore)/10:null,trailer:a.trailer?.site==='youtube'?{youtube_id:a.trailer.id}:null,background:a.bannerImage||'',year:a.seasonYear||a.startDate?.year,startDate:fuzzyDate(a.startDate),endDate:fuzzyDate(a.endDate),
    format:a.format,genres:a.genres,tags:(a.tags||[]).map(t=>t.name),age:a.isAdult?18:null,episodes:a.episodes,chapters:a.chapters,volumes:a.volumes,status:a.status,
    releases:[...(a.airingSchedule?.nodes||[]),...(a.nextAiringEpisode?[a.nextAiringEpisode]:[])].map(e=>({episode:e.episode,date:e.airingAt,kind:'original',provider:'anilist'})),
    ids:a.idMal?{mal:String(a.idMal)}:{},links:[{provider,url:a.siteUrl}]}));
  if(provider==='shikimori')return list(data).filter(a=>a?.id!=null&&(a.name||a.russian)).map(a=>record(provider,a.id,kind,{titles:{ru:a.russian,en:a.name,native:a.japanese?.[0]},aliases:[...(a.synonyms||[]),...(a.english||[]),...(a.japanese||[])],description:a.description,
    cover:imageURL(a.image?.original||''),score:Number(a.score)||null,episodesAired:a.episodes_aired??null,format:a.kind,genres:(a.genres||[]).map(g=>g.russian||g.name),episodes:a.episodes,chapters:a.chapters,volumes:a.volumes,
    status:a.status,startDate:a.aired_on,endDate:a.released_on,age:ageOf(a.rating),ageLabel:a.rating,ids:{mal:String(a.id)},links:[{provider,url:imageURL(a.url||'')}]}));
  if(provider==='jikan')return list(data.data).filter(a=>a&&/^\d+$/.test(String(a.mal_id))&&(a.title||a.title_english||a.russian)).map(a=>record(provider,a.mal_id,kind,{titles:{ru:a.russian,en:a.title_english,native:a.title_japanese},title:a.title,aliases:(a.titles||[]).map(t=>t.title),description:a.synopsis,
    cover:a.images?.webp?.large_image_url||a.images?.jpg?.large_image_url,format:a.type,year:a.year,genres:(a.genres||[]).map(g=>g.name),tags:[...(a.themes||[]),...(a.demographics||[])].map(t=>t.name),
    age:ageOf(a.rating),ageLabel:a.rating,episodes:a.episodes,chapters:a.chapters,volumes:a.volumes,status:a.status,startDate:a.aired?.from||a.published?.from,endDate:a.aired?.to||a.published?.to,
    score:Number(a.score)||null,trailer:a.trailer||null,episodesAired:a.episodes_aired??null,broadcast:a.broadcast?.string,ids:{mal:String(a.mal_id)},links:[{provider,url:a.url}]}));
  if(provider==='tvmaze')return list(data).map(value=>value.show||value).filter(a=>a.id).map(a=>record(provider,a.id,a.genres?.includes('Anime')?'anime':'tv',{
    title:a.name,description:a.summary,cover:a.image?.original||a.image?.medium,format:a.type,genres:a.genres,status:a.status,startDate:a.premiered,endDate:a.ended,
    ids:a.externals?.imdb?{imdb:a.externals.imdb}:{},episodes:a._embedded?.episodes?.length||null,episodeImages:Object.fromEntries((a._embedded?.episodes||[]).filter(e=>e.image?.medium||e.image?.original).map(e=>[String(e.season||1)+':'+e.number,safeImage(e.image.medium||e.image.original)])),
    releases:(a._embedded?.episodes||[]).filter(e=>e.airstamp).map(e=>({episode:e.number,season:e.season,date:e.airstamp,kind:'original',provider})),links:[{provider,url:a.url}]}));
  if(provider==='imdb'){
    if(data['@type'])return [record(provider,(data.url||'').match(/tt\d+/)?.[0]||'',kind,{title:data.name,description:data.description,cover:typeof data.image==='string'?data.image:data.image?.url,
      format:data['@type'],genres:list(data.genre),age:ageOf(data.contentRating),ageLabel:data.contentRating,startDate:data.datePublished,links:[{provider,url:data.url}]})];
    return (data.d||[]).filter(a=>a.id?.startsWith('tt')&&/movie|film|series|tv/i.test(a.qid||a.q||'')).map(a=>record(provider,a.id,/series/i.test(a.qid||a.q)?'tv':'movie',{title:a.l,cover:a.i?.imageUrl,year:a.y,format:a.q,ids:{imdb:a.id},description:'',links:[{provider,url:'https://www.imdb.com/title/'+a.id+'/'}]}));
  }
  if(provider==='openlibrary'){
    const cover=id=>Number(id)>0?'https://covers.openlibrary.org/b/id/'+Number(id)+'-L.jpg':'';
    const work=key=>String(key||'').match(/^\/works\/(OL\d{1,12}W)$/)?.[1];
    if(data?.key&&!data.docs){
      const id=work(data.key);if(!id)return [];
      const text=typeof data.description==='string'?data.description:data.description?.value||'';
      return [record(provider,id,'book',{title:data.title,titles:{en:data.title},description:text.replace(/\(\[source\]\[\d+\]\)|\[\d+\]: https?:\S+/g,'').trim(),
        cover:cover(data.covers?.find(c=>c>0)),format:'Книга',ids:{openlibrary:id},links:[{provider,url:'https://openlibrary.org/works/'+id}]})];
    }
    const local=data?.mvLanguage||'ru';
    // The default shelf is stories: popular fiction, not business or self-help.
    const stories=x=>!data?.mvStories||!(x.subject||[]).some(s=>/non-?fiction|self-help|business|success|finance|psycholog/i.test(s))&&(x.subject||[]).some(s=>/fiction|novel|fantasy|stories|роман|фантаст/i.test(s));
    return list(data?.docs).filter(x=>work(x.key)&&x.title&&stories(x)).map(x=>{
      const edition=x.editions?.docs?.[0]||{},id=work(x.key);
      // Transliterated edition titles ("Bogatyĭ papa") are worse than the original.
      const translated=edition.title&&/[Ѐ-ӿ]/.test(edition.title)?edition.title:'';
      return record(provider,id,'book',{titles:{[local]:translated||undefined,en:x.title},title:x.title,aliases:[x.title,translated],
        authors:(x.author_name||[]).slice(0,4),cover:cover(edition.cover_i)||cover(x.cover_i),year:x.first_publish_year||null,format:'Книга',
        ids:{openlibrary:id},description:'',links:[{provider,url:'https://openlibrary.org/works/'+id}]});
    });
  }
  if(provider==='fantlab'){
    const image=value=>value?safeImage(new URL(value,'https://fantlab.ru/').href):'';
    if(data?.work_id){
      const authors=(data.authors||[]).filter(a=>a.type==='autor').map(a=>a.name);
      return [record(provider,data.work_id,'book',{titles:{ru:data.work_name,en:data.work_name_orig||undefined},title:data.work_name,aliases:[data.work_name,data.work_name_orig,...(data.work_name_alts||[])],
        authors,description:String(data.work_description||'').replace(/\[[^\]]{1,40}\]/g,''),cover:image(data.image),year:data.work_year||null,format:'Книга',score:Number(data.rating?.rating)||null,
        ids:{fantlab:String(data.work_id)},links:[{provider,url:'https://fantlab.ru/work'+data.work_id}]})];
    }
    return list(data?.matches).filter(x=>/^\d{1,9}$/.test(String(x.work_id))&&String(x.rusname||x.name||'').trim()).map(x=>{
      const picture=x.pic_edition_id||x.pic_edition_id_auto;
      return record(provider,x.work_id,'book',{titles:{ru:String(x.rusname||'').trim()||undefined,en:String(x.name||'').trim()||undefined},title:String(x.rusname||x.name).trim(),
        aliases:[x.rusname,x.name,x.altname].map(v=>String(v||'').trim()),authors:String(x.all_autor_rusname||x.autor1_rusname||'').split(/,\s*/).filter(Boolean),
        cover:picture?'https://fantlab.ru/images/editions/big/'+Number(picture):'',year:Number(x.year)||null,format:x.name_show_im?x.name_show_im.replace(/^./,c=>c.toLocaleUpperCase('ru')):'Книга',
        score:Number(x.midmark?.[0])?Math.round(x.midmark[0]*10)/10:null,ids:{fantlab:String(x.work_id)},description:'',links:[{provider,url:'https://fantlab.ru/work'+x.work_id}]});
    });
  }
  if(provider==='kinobox'){
    const rows=data?.data?.movie?[data.data.movie]:list(data?.data?.items);
    return rows.filter(a=>/^\d{1,12}$/.test(String(a?.id))&&a.title?.russian).map(a=>{
      const poster=safeImage(a.gallery?.posterUrl||'').replace(/\/orig$/,'/600x900'),rating=a.rating||{};
      return record(provider,a.id,a.type==='Series'?'tv':'movie',{titles:{ru:a.title.russian,en:a.title.original||undefined},title:a.title.russian,aliases:[a.title.russian,a.title.original],
        description:a.synopsis||a.description||'',cover:poster,background:safeImage(a.gallery?.coverUrl||'').replace(/\/orig$/,'/1920x'),year:a.year||yearOf(a.releaseDate),startDate:a.releaseDate||null,
        format:a.type==='Series'?'Сериал':'Фильм',genres:(a.genres||[]).map(g=>String(g.name||'').replace(/^./,c=>c.toLocaleUpperCase('ru'))).filter(Boolean),
        tags:(a.countries||[]).map(c=>c.name).filter(Boolean),countries:(a.countries||[]).map(c=>c.name).filter(Boolean),score:Number(rating.kinopoisk?.value)||Number(rating.imdb?.value)||null,
        scores:[['kinopoisk','Кинопоиск','255 102 0','https://www.kinopoisk.ru/'+(a.type==='Series'?'series':'film')+'/'+a.id+'/'],['imdb','IMDb','245 197 24','']].filter(([key])=>Number(rating[key]?.value)>0).map(([key,name,rgb,url])=>({key,name,rgb,url,value:Number(rating[key].value),votes:Number(rating[key].count)||null})),duration:/^(\d+):(\d+)/.test(a.duration||'')?Number(a.duration.split(':')[0])*60+Number(a.duration.split(':')[1]):null,
        age:/age(\d+)/.test(a.restriction?.age||'')?Number(a.restriction.age.match(/age(\d+)/)[1]):null,ageLabel:/age(\d+)/.test(a.restriction?.age||'')?a.restriction.age.match(/age(\d+)/)[1]+'+':'',
        ids:{kinopoisk:String(a.id)},links:[{provider,url:'https://www.kinopoisk.ru/'+(a.type==='Series'?'series':'film')+'/'+a.id+'/'}]});
    });
  }
  if(provider==='wikidata')return (data.search||[]).filter(a=>/film|фильм|映画|영화|电影|сериал|television/i.test(a.description||'')).map(a=>record(provider,a.id,/сериал|series|television/i.test(a.description||'')?'tv':'movie',{title:a.label,description:a.description,aliases:a.aliases,links:[{provider,url:a.concepturi||'https://www.wikidata.org/wiki/'+a.id}]}));
  return [];
}

export function mergeCatalog(values){
  const result=[],list=value=>Array.isArray(value)?value:[];
  for(const value of values){
    // Saved/deep-linked titles can be partial while catalogue enrichment loads.
    // Give both sides the same collection shape before merging either order.
    const item={...value,providers:unique([...list(value.providers),value.provider]),
      aliases:unique([...list(value.aliases),value.title,...Object.values(value.titles||{})]),
      genres:list(value.genres),tags:list(value.tags),links:list(value.links),releases:list(value.releases),
      ids:value.ids||{},titles:value.titles||{}};
    const current=result.find(other=>other.kind===item.kind&&(
      Object.keys(item.ids||{}).some(key=>item.ids[key]&&item.ids[key]===other.ids?.[key])||
      ((!item.ids?.mal||!other.ids?.mal||item.ids.mal===other.ids.mal)&&(!item.year||!other.year||item.year===other.year)&&item.aliases.some(alias=>normalized(alias).length>3&&other.aliases.some(x=>normalized(x)===normalized(alias))))));
    if(!current){result.push({...item});continue;}
    current.providers=unique([...current.providers,...item.providers]);current.aliases=unique([...current.aliases,...item.aliases]);
    current.genres=unique([...current.genres,...item.genres]);current.tags=unique([...current.tags,...item.tags]);current.links=[...current.links,...item.links];current.ids={...current.ids,...item.ids};
    current.releases=[...current.releases,...item.releases].filter((e,i,a)=>a.findIndex(x=>x.date===e.date&&x.episode===e.episode)===i);
    if(item.titles.ru){current.titles={...current.titles,...item.titles};current.title=item.titles.ru;current.description=item.description||current.description;}
    for(const key of ['cover','description','year','format','age','ageLabel','episodes','chapters','volumes','status','startDate','endDate','score','trailer','background','episodesAired','duration','authors'])if(current[key]==null||current[key]==='')current[key]=item[key];
    for(const key of ['scores','countries'])if(!current[key]?.length&&item[key]?.length)current[key]=item[key];
  }
  return result;
}

export function matchesFilters(item,filters){
  if(filters.year&&String(item.year)!==String(filters.year))return false;
    const manga=item.kind==='manga'||globalContentPolicy(),match=(left,right)=>manga?(mangaPolicy().key(right)?mangaPolicy().key(left)===mangaPolicy().key(right):!globalContentPolicy()&&normalized(left).includes(normalized(right))):normalized(localLabel(left)).includes(normalized(localLabel(right)))||normalized(left).includes(normalized(right));
  if(filters.genre&&!item.genres.some(g=>manga?match(g,filters.genre):normalized(genreLabels[g]||localLabel(g)).includes(normalized(localLabel(filters.genre)))))return false;
  if(filters.tag&&!String(filters.tag).split(',').map(s=>s.trim()).filter(Boolean).every(tag=>(item.tags||[]).concat(item.genres||[]).some(t=>match(t,tag))))return false;
  const formatKey=value=>({манга:'manga',манхва:'manhwa',маньхуа:'manhua',вебтун:'webtoon'}[normalized(value)]||normalized(value));
  if(filters.format&&formatKey(item.format)!==formatKey(filters.format))return false;
  if(filters.age==='under18'&&(item.age==null||item.age>=18))return false;
  if(filters.age==='adult'&&(item.age==null||item.age<18))return false;
  return true;
}

const OPEN_LIBRARY_FIELDS='key,title,author_name,cover_i,first_publish_year,subject,editions,editions.title,editions.cover_i,editions.language';
// Books: Open Library (popular editions in Russian/Ukrainian, with covers) and
// Fantlab (Russian base). Both allow browser requests; no server is needed.
export function bookLanguage(){const value=contentLanguage();return value==='uk'||value==='all'&&uiLanguage()==='uk'?'uk':'ru';}
export function providerUrl(provider,{query='',kind='anime',page=1,identity,year,genre,tag,server=''}){
  if(provider==='openlibrary'){
    if(identity)return 'https://openlibrary.org/works/'+encodeURIComponent(identity)+'.json';
    const language=bookLanguage(),url=new URL('https://openlibrary.org/search.json');
    const terms=[query||'language:'+(language==='uk'?'ukr':'rus'),year?'first_publish_year:'+Number(year):'',genre?'subject:"'+String(genre).replace(/"/g,'')+'"':''].filter(Boolean);
    url.searchParams.set('q',terms.join(' '));if(!query)url.searchParams.set('sort','readinglog');url.searchParams.set('lang',language);
    url.searchParams.set('limit',query||genre?16:32);url.searchParams.set('page',page);url.searchParams.set('fields',OPEN_LIBRARY_FIELDS);return url.href;
  }
  if(provider==='fantlab')return identity?'https://api.fantlab.ru/work/'+encodeURIComponent(identity):'https://api.fantlab.ru/search-works?'+new URLSearchParams({q:query,page:String(page)});
  if(server){const url=new URL('metadata/'+provider,server+'/');for(const [key,value]of Object.entries({q:query,kind,page,identity,year,genre:queryLabel(genre),tag:String(tag||'').split(',').map(t=>queryLabel(t.trim())).join(',')}))if(value)url.searchParams.set(key,value);return url.href;}
  const resource=['manga','ranobe'].includes(kind)?'manga':'anime';
  if(provider==='kitsu'){
    const url=new URL('https://kitsu.io/api/edge/'+resource+(identity?'/'+identity:''));url.searchParams.set('include','genres,categories,mappings');
    if(!identity){url.searchParams.set('page[limit]',16);url.searchParams.set('page[offset]',(page-1)*16);if(query)url.searchParams.set('filter[text]',query);else url.searchParams.set('sort','-userCount');if(year&&resource==='anime')url.searchParams.set('filter[seasonYear]',year);if(kind==='ranobe')url.searchParams.set('filter[subtype]','novel');}
    return url.href;
  }
  if(provider==='shikimori'){const url=new URL('https://shikimori.io/api/'+(resource==='anime'?'animes':kind==='ranobe'&&!identity?'ranobe':'mangas')+(identity?'/'+identity:''));if(!identity){url.searchParams.set('search',query);url.searchParams.set('limit',16);url.searchParams.set('page',page);url.searchParams.set('order','popularity');if(year)url.searchParams.set('season',year);}return url.href;}
  if(provider==='jikan'){const url=new URL('https://api.jikan.moe/v4/'+resource+(identity?'/'+identity+'/full':''));if(!identity){url.searchParams.set('q',query);url.searchParams.set('limit',16);url.searchParams.set('page',page);if(kind==='ranobe')url.searchParams.set('type','lightnovel');}return url.href;}
  if(provider==='tvmaze')return identity?'https://api.tvmaze.com/shows/'+identity+'?embed=episodes':'https://api.tvmaze.com/search/shows?q='+encodeURIComponent(query);
  if(provider==='wikidata')return 'https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&origin=*&language='+(/[А-Яа-яЁё]/.test(query)?'ru':/[ぁ-ヿ]/.test(query)?'ja':/[가-힣]/.test(query)?'ko':/[一-鿿]/.test(query)?'zh':'en')+'&search='+encodeURIComponent(query)+'&limit=20';
  if(provider==='anilist')return 'https://graphql.anilist.co';
  throw Error('Для этого каталога нужно подключить сервер импорта.');
}

const aniFields='id idMal title{romaji english native} synonyms description coverImage{large} bannerImage trailer{id site thumbnail} averageScore format status genres tags{name} isAdult episodes chapters volumes seasonYear startDate{year month day} endDate{year month day} siteUrl nextAiringEpisode{episode airingAt} airingSchedule(perPage:50,notYetAired:true){nodes{episode airingAt}}';
// How many pages a provider can list for this request (16 titles per page), when it says so.
export function catalogPages(provider,data){
  const count=provider==='kitsu'?Math.ceil(Number(data?.meta?.count)/16):provider==='anilist'?Number(data?.data?.Page?.pageInfo?.lastPage):0;
  return Number.isFinite(count)&&count>0?Math.min(count,100000):null;
}
export async function fetchCatalog(provider,options,fetcher=fetch){
  options.signal?.throwIfAborted();
  const url=providerUrl(provider,options),abort=new AbortController(),signal=options.signal;
  const stop=()=>abort.abort();signal?.addEventListener('abort',stop,{once:true});
  const timeout=setTimeout(stop,16000);
  try{
    const init={signal:abort.signal};
    if(provider==='anilist'&&!options.server){init.method='POST';init.headers={'Content-Type':'application/json'};init.body=JSON.stringify(options.identity?{query:`query($id:Int){Media(id:$id){${aniFields}}}`,variables:{id:Number(options.identity)}}:{query:`query($search:String,$type:MediaType,$page:Int){Page(page:$page,perPage:16){pageInfo{lastPage} media(type:$type,sort:POPULARITY_DESC${options.kind==='ranobe'?',format_in:[NOVEL]':options.kind==='manga'?',format_not_in:[NOVEL]':''}${options.query?',search:$search':''}){${aniFields}}}}`,variables:{search:options.query||null,type:['manga','ranobe'].includes(options.kind)?'MANGA':'ANIME',page:options.page||1}});}
    const response=await fetcher(url,init);
    if(!response.ok)throw Error(response.status===429?'Слишком частые запросы':'Каталог временно недоступен');
    const data=await response.json();if(data.errors)throw Error('Каталог не ответил на запрос');
    if(provider==='openlibrary'&&data&&typeof data==='object'){data.mvLanguage=bookLanguage();data.mvStories=!options.query&&!options.genre;}
    let items=normalizeCatalog(provider,data,options.kind);
    const pages=catalogPages(provider,data);
    if(provider==='openlibrary'&&!options.identity&&data?.mvLanguage==='ru')items=await russianBookTitles(items,options.signal,fetcher);
    const alternate=!options.identity&&!options.spellingFallback&&['kitsu','anilist','jikan'].includes(provider)&&alternateSpelling(options.query);
    if(!items.length&&alternate){
      clearTimeout(timeout);options.signal?.throwIfAborted();
      return (await fetchCatalog(provider,{...options,query:alternate,spellingFallback:true},fetcher)).map(item=>({...item,searchSpelling:alternate}));
    }
    if(pages)Object.defineProperty(items,'pages',{value:pages,enumerable:false});
    return items;
  }catch(error){
    signal?.throwIfAborted();
    // Free metadata hosts can be reachable from a browser while rejecting a
    // datacentre IP (or vice versa). IMDb needs the relay because it lacks CORS.
    // This fallback never handles source pages, playlists or media bytes.
    if(options.server&&!['imdb','kinobox','openlibrary','fantlab'].includes(provider)){
      clearTimeout(timeout);
      return await fetchCatalog(provider,{...options,server:''},fetcher);
    }
    throw error;
  }finally{clearTimeout(timeout);signal?.removeEventListener('abort',stop);}
}
// Open Library often lacks the Russian edition; Fantlab (Russian base) names
// the same work by its original title. Only an exact original-title match is used.
async function russianBookTitles(items,signal,fetcher){
  const missing=items.filter(item=>!item.titles.ru&&item.titles.en).slice(0,16);
  await Promise.all(missing.map(async item=>{
    try{
      const response=await fetcher('https://api.fantlab.ru/search-works?'+new URLSearchParams({q:item.titles.en,page:'1'}),{signal:AbortSignal.any([signal,AbortSignal.timeout(6000)].filter(Boolean))});
      if(!response.ok)return;
      const match=((await response.json()).matches||[]).find(x=>x.rusname&&normalized(x.name)===normalized(item.titles.en));
      if(match){const ru=String(match.rusname).trim();item.titles={...item.titles,ru};item.title=ru;item.aliases=unique([ru,...item.aliases]);item.ids={...item.ids,fantlab:String(match.work_id)};}
    }catch{}
  }));
  return items;
}
// Browsing without a query pages through ONE ordered list (AniList), so page 5
// never repeats page 1 the way three independently sorted catalogues did.
// Shikimori only adds Russian names to the titles of that page.
export const BROWSE_KINDS=['anime','manga','ranobe'];
export const CATALOG_SORTS=[['popular','По популярности'],['trending','Сейчас обсуждают'],['score','По рейтингу'],['favourites','Чаще в избранном'],['new','Сначала новые'],['old','Сначала старые'],['title','По названию'],['length','Больше серий и глав']];
const ANILIST_GENRES=new Set(['Action','Adventure','Comedy','Drama','Ecchi','Fantasy','Hentai','Horror','Mahou Shoujo','Mecha','Music','Mystery','Psychological','Romance','Sci-Fi','Slice of Life','Sports','Supernatural','Thriller']);
const ANILIST_FORMATS=new Set(['TV','TV_SHORT','MOVIE','SPECIAL','OVA','ONA','MUSIC','MANGA','NOVEL','ONE_SHOT']);
export function browseQuery({kind='anime',page=1,perPage=24,sort='popular',year,genre,tag,format}={}){
  const manga=kind!=='anime',order={popular:'POPULARITY_DESC',trending:'TRENDING_DESC',score:'SCORE_DESC',favourites:'FAVOURITES_DESC',new:'START_DATE_DESC',old:'START_DATE',title:'TITLE_ROMAJI',length:manga?'CHAPTERS_DESC':'EPISODES_DESC'}[sort]||'POPULARITY_DESC';
  // ID breaks ties, so equal scores keep one place across page requests.
  const args=['type:$type','sort:[$sort,ID]'],variables={type:manga?'MANGA':'ANIME',sort:order,page:Math.max(1,Number(page)||1),perPage:Math.min(50,Math.max(1,Number(perPage)||24))},defs=['$type:MediaType','$sort:MediaSort','$page:Int','$perPage:Int'];
  const add=(name,type,value,arg=name)=>{defs.push('$'+name+':'+type);args.push(arg+':$'+name);variables[name]=value;};
  const pickedFormat=String(format||'').toUpperCase().replace(/\s+/g,'_');
  if(ANILIST_FORMATS.has(pickedFormat))add('format','[MediaFormat]',[pickedFormat],'format_in');
  else if(kind==='ranobe')add('format','[MediaFormat]',['NOVEL'],'format_in');
  else if(kind==='manga')add('notFormat','[MediaFormat]',['NOVEL'],'format_not_in');
  if(year&&/^\d{4}$/.test(String(year))){if(manga){add('from','FuzzyDateInt',Number(year)*10000,'startDate_greater');add('to','FuzzyDateInt',(Number(year)+1)*10000,'startDate_lesser');}else add('year','Int',Number(year),'seasonYear');}
  // Dated sorts would otherwise open with undated announcements.
  else if(sort==='new'||sort==='old')add('dated','FuzzyDateInt',10000000,'startDate_greater');
  const labels=[genre,...String(tag||'').split(',')].map(v=>String(v||'').trim()).filter(Boolean).map(queryLabel);
  const genres=labels.filter(v=>ANILIST_GENRES.has(v)),tags=labels.filter(v=>!ANILIST_GENRES.has(v));
  if(genres.length)add('genres','[String]',genres,'genre_in');
  if(tags.length)add('tags','[String]',tags,'tag_in');
  return {query:'query('+defs.join(',')+'){Page(page:$page,perPage:$perPage){pageInfo{lastPage total} media('+args.join(',')+'){'+aniFields+'}}}',variables};
}
export async function fetchBrowsePage(options,fetcher=fetch){
  const {kind='anime',signal}=options;
  const response=await fetcher('https://graphql.anilist.co',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(browseQuery(options)),signal:AbortSignal.any([signal,AbortSignal.timeout(16000)].filter(Boolean))});
  if(!response.ok)throw Error(response.status===429?'Слишком частые запросы':'Каталог временно недоступен');
  const data=await response.json();if(data.errors)throw Error('Каталог не ответил на запрос');
  const spine=normalizeCatalog('anilist',data,kind),pages=catalogPages('anilist',data);
  const ids=[...new Set(spine.map(item=>item.ids?.mal).filter(Boolean))];let names=[];
  if(ids.length){
    try{
      const url=new URL('https://shikimori.io/api/'+(kind==='anime'?'animes':kind==='ranobe'?'ranobe':'mangas'));url.searchParams.set('ids',ids.join(','));url.searchParams.set('limit',String(Math.min(50,ids.length)));
      const reply=await fetcher(url.href,{signal:AbortSignal.any([signal,AbortSignal.timeout(8000)].filter(Boolean))});
      if(reply.ok)names=normalizeCatalog('shikimori',await reply.json(),kind).filter(item=>ids.includes(item.ids?.mal));
    }catch(error){signal?.throwIfAborted();}
  }
  const items=mergeCatalog([...spine,...names]).slice(0,spine.length);
  Object.defineProperty(items,'pages',{value:pages,enumerable:false});
  Object.defineProperty(items,'russian',{value:names.length>0,enumerable:false});
  return items;
}

export function catalogProviders(kind,query,server){
  // Kinobox (Kinopoisk) is the Russian film base: popular lists without a
  // query and Russian titles. IMDb/TVmaze/Wikidata add English titles when searching.
  if(['movie','tv'].includes(kind))return [...(server?['kinobox']:[]),...(server&&query?['imdb']:[]),...(query?(kind==='tv'?['tvmaze','wikidata']:['wikidata']):[])];
  // Shikimori is the Russian base; AniList/Kitsu/Jikan are English. Duplicates merge.
  if(kind==='ranobe')return ['shikimori','anilist','kitsu',...(query?['jikan']:[])];
  if(kind==='book')return ['openlibrary',...(query?['fantlab']:[])];
  return ['kitsu','shikimori','anilist',...(query?['jikan']:[])];
}
