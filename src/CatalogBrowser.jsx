import React,{useEffect,useMemo,useState} from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import {motion,useReducedMotion} from 'motion/react';
import Icon from './Icons.jsx';
import Artwork from './Artwork.jsx';
import {fetchCatalog,genreLabels,matchesFilters,mergeCatalog,providers,safeImage} from './catalog.js';
import {useCatalog} from './use-catalog.js';
import {kinds,Poster,ReleaseCalendar} from './ImportParts.jsx';
import ImportSelection from './ImportSelection.jsx';
import CatalogSearch from './CatalogSearch.jsx';
import {tagLabels,localLabel,russianLabels} from './taxonomy.js';
import {translate} from './title-metadata.js';
import PlatformRatings from './PlatformRatings.jsx';
import {useVoices} from './use-voices.js';
const noTitles=Object.freeze([]);

export function TitleDetails({value,service,state,onBack,onSubmitted,onOpenLibrary}){
  const [item,setItem]=useState(value),[tab,setTab]=useState('import'),[loading,setLoading]=useState(false);
  useEffect(()=>{
    const abort=new AbortController();setItem(value);setLoading(true);
    fetchCatalog(value.provider,{identity:value.providerId,kind:value.kind,server:service.server,signal:abort.signal}).then(found=>{if(!abort.signal.aborted&&found.length)setItem(mergeCatalog([value,...found])[0]);}).catch(()=>{}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[value.id,service.server]);
  return <section className="catalog-detail"><button className="text-link catalog-back" onClick={onBack}><Icon name="back" size={16}/>К результатам поиска</button>
    <div className="import-dossier-layout"><div className="import-dossier-main"><div className="detail-hero"><div className="detail-poster"><Poster item={item}/></div><div className="detail-copy"><span className="eyebrow">{kinds.find(k=>k[0]===item.kind)?.[1]||'Произведение'}{loading?' · обновляем сведения':''}</span><h2>{item.title}</h2><div className="detail-facts">{item.year&&<span>{item.year}</span>}{item.format&&<span>{translate(item.format)}</span>}{item.ageLabel&&<span>{item.ageLabel}</span>}{item.episodes&&<span>{item.episodes} серий</span>}</div><div className="detail-genres">{item.genres.map(genre=><span key={genre}>{genreLabels[genre]||genre}</span>)}</div></div></div>
      <p className="detail-description">{item.description||'Русское описание пока не предоставлено каталогом.'}</p>
      <PlatformRatings identity={item.ids?.mal} kind={item.kind} server={service.server} compact/>
      <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="import-tabs" aria-label="Карточка тайтла"><Tabs.Trigger value="import">О произведении</Tabs.Trigger><Tabs.Trigger value="calendar">Календарь</Tabs.Trigger><Tabs.Trigger value="about">Подробности</Tabs.Trigger></Tabs.List>
        <Tabs.Content value="import"><div className="detail-tags">{russianLabels(item.tags).slice(0,18).map(tag=><span key={tag}>{tag}</span>)}</div><p className="fine">Озвучки справа собраны только для выбранного тайтла и года. Другой сезон выбирается отдельной карточкой.</p></Tabs.Content>
        <Tabs.Content value="calendar"><ReleaseCalendar items={[item]}/></Tabs.Content>
        <Tabs.Content value="about"><dl className="title-information"><div><dt>Начало выпуска</dt><dd>{item.startDate?.slice(0,10)||'Не указано'}</dd></div><div><dt>Окончание выпуска</dt><dd>{item.endDate?.slice(0,10)||'Не указано'}</dd></div><div><dt>Каталоги</dt><dd>{item.providers.map(p=>providers[p]).join(' · ')}</dd></div></dl></Tabs.Content>
      </Tabs.Root></div><aside className="import-dossier-panel"><ImportSelection onOpenLibrary={onOpenLibrary} item={item} state={state} service={service} onSubmitted={onSubmitted}/></aside></div>
  </section>;
}

export default function CatalogBrowser({service,state,onSubmitted,onItems,onOpenLibrary,initialQuery,initialKind,initialTarget,initialItem}){
  const preset=initialTarget||initialItem;
  const [query,setQuery]=useState(initialQuery||''),[kind,setKind]=useState(initialKind||'anime'),[selected,setSelected]=useState(preset||null);
  const [filters,setFilters]=useState({year:'',genre:'',tag:'',format:'',age:''}),[voice,setVoice]=useState(''),[showFilters,setShowFilters]=useState(false),[page,setPage]=useState(1),[composing,setComposing]=useState(false);
  useEffect(()=>{if(preset)setSelected(preset);},[preset]);
  const reduced=useReducedMotion();
  const {items,statuses,loading,retry}=useCatalog(query,kind,filters.year,service.server,page,composing,filters);
  useEffect(()=>onItems?.(items),[items]);
  const voices=useVoices(kind==='anime'?items:noTitles,voice,service);
  const visible=useMemo(()=>items.filter(item=>matchesFilters(item,filters)&&item.kind===kind&&(!voice||(voices.results[item.id]?.dubs||[]).some(d=>d.toLocaleLowerCase().includes(voice.toLocaleLowerCase())))),[items,filters,kind,voice,voices.results]);
  const genres=[...new Set([...Object.values(genreLabels),...items.flatMap(item=>item.genres.map(localLabel))])].sort((a,b)=>a.localeCompare(b,'ru'));
  const formats=[...new Set(items.map(item=>item.format).filter(Boolean))];
  const suggestions=visible.slice(0,7),filter=(key,value)=>{setFilters(old=>({...old,[key]:value}));setPage(1);};
  function choose(item){setSelected(item);}
  const spelling=visible.find(item=>item.searchSpelling)?.searchSpelling;
  const unavailable=Object.values(statuses).includes('unavailable');
  if(selected)return <TitleDetails onOpenLibrary={onOpenLibrary} value={selected} service={service} state={state} onBack={()=>setSelected(null)} onSubmitted={onSubmitted}/>;
  return <><motion.section className="catalog-intro" initial={reduced?false:{opacity:0,y:8}} animate={{opacity:1,y:0}}><span className="server-tag"><i/> ОТКРЫВАЙ НОВЫЕ ИСТОРИИ</span><h2>Миров больше,<br/><em>чем кажется.</em></h2><p>Аниме, манга и кино из бесплатных каталогов.<br/>Импорт — прямо с сервера в твой Google Drive.</p><div className="catalog-orbit"><Artwork hero/></div></motion.section>
    <div className="catalog-kind-row" aria-label="Тип произведения">{kinds.map(([id,label])=><button key={id} className={'chip'+(kind===id?' chip-active':'')} onClick={()=>{setKind(id);setVoice('');setFilters({year:'',genre:'',tag:'',format:'',age:''});setPage(1);}}>{label}</button>)}</div>
    <CatalogSearch query={query} onQuery={value=>{setQuery(value);setPage(1);}} suggestions={suggestions} loading={loading} showFilters={showFilters} onToggleFilters={()=>setShowFilters(value=>!value)} onChoose={choose} onComposing={setComposing}/>
    <p className="catalog-search-hint">Начни печатать — подсказки и карточки обновятся сами.</p>
    {showFilters&&<section className="catalog-filters"><label>Год<input className="field-input" type="number" min="1880" max="2100" value={filters.year} onChange={e=>filter('year',e.target.value)} placeholder="Любой"/></label><label>Жанр<select className="field-input" value={filters.genre} onChange={e=>filter('genre',e.target.value)}><option value="">Все жанры</option>{genres.map(g=><option key={g}>{g}</option>)}</select></label><label>Тег<input className="field-input" value={filters.tag} onChange={e=>filter('tag',e.target.value)} list="catalogTags" placeholder="Например, путешествия во времени"/><datalist id="catalogTags">{[...new Set([...Object.values(tagLabels),...items.flatMap(item=>item.tags.map(localLabel))])].map(t=><option key={t} value={t}/>)}</datalist></label><label>Формат<select className="field-input" value={filters.format} onChange={e=>filter('format',e.target.value)}><option value="">Все форматы</option>{formats.map(f=><option key={f}>{f}</option>)}</select></label><label>Возраст<select className="field-input" value={filters.age} onChange={e=>filter('age',e.target.value)}><option value="">Все, включая неизвестный</option><option value="under18">До 18 · если указан</option><option value="adult">18+</option></select></label><label>Озвучка<input id="voiceFilter" className="field-input" value={voice} onChange={e=>setVoice(e.target.value)} disabled={kind!=='anime'||service.status!=='connected'} list="voiceStudios" placeholder="Например, AniDub"/><datalist id="voiceStudios">{[...new Set(Object.values(voices.results).flatMap(v=>v.dubs||[]))].map(name=><option key={name} value={name}/>)}</datalist></label><p className="fine">{voice?`Проверяем озвучки найденных карточек по HTML источников. Осталось: ${voices.pending}. `:'Фильтр озвучки доступен после подключения сервера. '}Жанры и теги передаются в поддерживающие их каталоги; результаты дополнительно проверяются по выбранным фильтрам. Озвучки проверяются для первых 24 карточек страницы; отсутствие ответа не означает отсутствие перевода.</p></section>}
    <div className="catalog-provider-row" aria-label="Источники метаданных">{Object.entries(statuses).map(([id,status])=><span key={id} className={'catalog-provider provider-'+status} title={status==='unavailable'?'Сейчас недоступен; поиск идёт в остальных каталогах':providers[id]}><i/>{providers[id]}</span>)}{unavailable&&<button className="catalog-retry" disabled={loading} onClick={retry}><Icon name="refresh" size={13}/>Повторить поиск</button>}</div>{spelling&&<p className="fine catalog-spelling">Также ищем по написанию «{spelling}»</p>}<div className="section-heading"><h2 className="section-title">{query?'Нашлось для тебя':'С чего начнётся история?'}</h2><span className="fine" role="status" aria-live="polite">{loading?'Обновляем карточки…':visible.length?visible.length+' тайтлов':''}</span></div>
    {visible.length?<div className="media-grid catalog-grid">{visible.map(item=><motion.article key={item.id} className="media-card catalog-card" whileHover={reduced?undefined:{y:-3}} whileTap={reduced?undefined:{scale:.985}}><button className="media-open" onClick={()=>choose(item)} aria-label={'Выбрать '+item.title}><div className="media-cover"><Poster item={item}/>{item.year&&<span className="catalog-year">{item.year}</span>}{item.age!=null&&<span className="catalog-age">{item.age}+</span>}<span className="media-open-indicator"><Icon name="plus" size={24}/></span></div><h3 className="media-name">{item.title}</h3><p className="media-meta">{[item.format,item.episodes?item.episodes+' сер.':item.chapters?item.chapters+' гл.':null].filter(Boolean).join(' · ')||providers[item.provider]}</p><p className="catalog-card-genres">{item.genres.slice(0,2).map(g=>genreLabels[g]||g).join(' · ')}</p></button></motion.article>)}</div>:<div className="catalog-empty">{loading?<><span className="loading-ring"/><p>Собираем ответы каталогов…</p></>:<><Icon name="search" size={32}/><p>{query?'Пока ничего не нашлось':'Начни вводить название'}</p><small>{Object.values(statuses).some(s=>s==='unavailable')?'Некоторые каталоги недоступны. Попробуй другое написание или повтори поиск позже.':'Можно искать на русском, английском, японском, китайском и корейском. Результат зависит от названий и синонимов в каталогах.'}</small></>}</div>}
    {visible.length>0&&<div className="catalog-pagination"><button className="btn btn-secondary" disabled={page===1||loading} onClick={()=>setPage(p=>p-1)}>Назад</button><span>Страница {page}</span><button className="btn btn-secondary" disabled={loading||items.length<16} onClick={()=>setPage(p=>p+1)}>Дальше<Icon name="arrow" size={15}/></button></div>}<p className="catalog-footnote">Метаданные: Kitsu, AniList, Shikimori, MyAnimeList, IMDb, TVmaze и Wikidata. Доступность источников различается. Все подключения без платных API-ключей.</p>
  </>;
}
