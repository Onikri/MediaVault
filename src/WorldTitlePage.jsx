import {useEffect,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {fetchCatalog,mergeCatalog} from './catalog.js';
import {loadTitleProfile,loadCharacter} from './title-metadata.js';
import {Poster} from './ImportParts.jsx';
import ImportSelection from './ImportSelection.jsx';
import PlatformRatings from './PlatformRatings.jsx';
import CreditsPanel from './CreditsPanel.jsx';
import Soundtrack from './Soundtrack.jsx';
import Icon from './Icons.jsx';
import {OnlineBooks} from './OnlineLibrary.jsx';
import {translate} from './title-metadata.js';

export default function WorldTitlePage({value,service,state,onBack,onSubmitted,onOpenLibrary,destination='online',onRelated}){
 const [item,setItem]=useState(value),[profile,setProfile]=useState(null),[loading,setLoading]=useState(false),[target,setTarget]=useState(destination),[character,setCharacter]=useState(null),[characterBusy,setCharacterBusy]=useState(false);
 useEffect(()=>{const abort=new AbortController();setItem(value);setProfile(null);setTarget(destination);setLoading(true);
  async function enrich(){try{if(!value.sourceOnly&&value.providerId){const rows=await fetchCatalog(value.provider,{identity:value.providerId,kind:value.kind,server:service.server,signal:abort.signal});if(!abort.signal.aborted&&rows.length)setItem(mergeCatalog([value,...rows])[0]);}
   if(value.ids?.mal){const p=await loadTitleProfile(value.ids.mal,value.kind,{server:service.server,signal:abort.signal});if(!abort.signal.aborted)setProfile(p);}
  }catch{}finally{if(!abort.signal.aborted)setLoading(false);}}
  enrich();return()=>abort.abort();
 },[value.id,service.server,destination]);
 const p=profile||{},name=p.title||item.title,genres=p.genres?.length?p.genres:item.genres||[],tags=p.tags?.length?p.tags:item.tags||[];
 async function openCharacter(c){setCharacter(c);setCharacterBusy(true);try{const data=await loadCharacter(c.id,{server:service.server});setCharacter(old=>old?.id===c.id?{...c,...data}:old);}catch{}finally{setCharacterBusy(false);}}
 return <article className="world-title"><button className="text-link catalog-back" onClick={onBack}><Icon name="back" size={16}/>К результатам поиска</button><div className="world-title-grid"><div className="world-title-main"><header className="world-title-hero"><div className="world-title-cover"><Poster item={{...item,cover:p.cover||item.cover}}/></div><div><span className="eyebrow">{item.kind==='anime'?'Аниме':item.kind==='ranobe'?'Ранобэ':item.kind==='manga'?'Манга и манхва':'Произведение'}{loading?' · обновляем сведения':''}</span><h1>{name}</h1><p className="world-native-title">{item.titles?.native||item.titles?.en||''}</p><div className="detail-facts">{item.year&&<span>{item.year}</span>}{item.format&&<span>{translate(item.format)}</span>}{item.ageLabel&&<span>{item.ageLabel}</span>}{(p.status||item.status)&&<span>{translate(p.status||item.status)}</span>}</div><div className="detail-genres">{genres.slice(0,8).map(g=><span key={g}>{g}</span>)}</div></div></header>
  <div className="world-description"><h2>История</h2><p>{p.description||item.description||'В источнике пока нет описания. Доступные главы можно открыть справа.'}</p></div><PlatformRatings identity={item.ids?.mal} kind={item.kind} server={service.server} compact/>
  {!!tags.length&&<div className="detail-tags">{tags.slice(0,18).map(t=><span key={t}>{t}</span>)}</div>}
  {!!p.characters?.length&&<section className="world-characters"><div className="section-heading"><h2>Персонажи</h2></div><div className="world-character-list">{p.characters.map(c=><button key={c.id} onClick={()=>openCharacter(c)}><span>{c.image?<img src={c.image} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<Icon name="user"/>}</span><strong>{c.name}</strong><small>{c.role||''}</small><span className="world-character-hint">{c.description||'Открыть сведения о персонаже'}</span></button>)}</div></section>}
  {item.kind==='anime'&&item.ids?.mal&&<Soundtrack identity={item.ids.mal} userId={state.user?.sub} animeTitle={name}/>}<CreditsPanel profile={p} server={service.server} renderArtwork={v=>v.image?<img src={v.image} alt="" loading="lazy" referrerPolicy="no-referrer"/>:null}/>
  {!!p.related?.length&&<section className="world-related"><div className="section-heading"><h2>В этой вселенной</h2></div><div className="world-related-list">{p.related.map(r=><button key={r.kind+':'+r.id} onClick={()=>onRelated?.(r)}><span>{r.cover&&<img src={r.cover} alt="" loading="lazy" referrerPolicy="no-referrer"/>}</span><strong>{r.title}</strong><small>{r.relation||r.format}</small></button>)}</div></section>}
 </div><aside className="world-title-play"><div className="world-watch-heading"><span className="eyebrow">Твоя следующая история</span><h2>{item.kind==='manga'||item.kind==='ranobe'?'Читать':'Смотреть'} здесь</h2><p>Онлайн — сразу. Любимые главы и серии можно сохранить.</p></div>{item.kind!=='ranobe'&&<div className="world-destinations" role="group" aria-label="Открыть или сохранить"><button aria-pressed={target==='online'} onClick={()=>setTarget('online')}>Онлайн</button><button aria-pressed={target==='drive'} onClick={()=>setTarget('drive')}>В Google Диск</button><button aria-pressed={target==='local'} onClick={()=>setTarget('local')}>На устройство</button></div>}{item.kind==='ranobe'?<><p className="fine">Автоматический источник этой книги пока не подключён. Можно открыть EPUB, PDF, FB2 или TXT по прямой ссылке либо с устройства.</p><OnlineBooks userId={state.user?.sub}/></>:<ImportSelection compact key={item.id} destination={target} onOpenLibrary={onOpenLibrary} item={item} state={state} service={service} onSubmitted={onSubmitted}/>}</aside></div>
 <Dialog.Root open={!!character} onOpenChange={open=>{if(!open)setCharacter(null);}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog character-dialog"><Dialog.Close className="icon-button dialog-close" aria-label="Закрыть персонажа"><Icon name="close"/></Dialog.Close><Dialog.Title>{character?.name}</Dialog.Title><Dialog.Description>{characterBusy?'Загружаем сведения…':character?.description||'Описание отсутствует в каталоге.'}</Dialog.Description>{character?.image&&<img src={character.image} alt="" referrerPolicy="no-referrer"/>}</Dialog.Content></Dialog.Portal></Dialog.Root></article>;
}
