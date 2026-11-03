import {useState,useEffect} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {X,ExternalLink,BookOpen,Tv} from 'lucide-react';
import {browseHref} from './anime-navigation.js';

export default function CharacterDialog({character,busy,error,onClose,renderArtwork,onRelated}){
 const [spoilers,setSpoilers]=useState(false);useEffect(()=>setSpoilers(false),[character?.id]);
 const attributes=character?.attributes||[],basic=attributes.filter(a=>!a.spoiler),extra=attributes.filter(a=>a.spoiler);
 return <Dialog.Root open={!!character} onOpenChange={open=>{if(!open)onClose();}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog character-dialog character-sheet">
 <header className="entity-dialog-heading"><div><p className="eyebrow">Персонаж</p><Dialog.Title>{character?.name}</Dialog.Title><Dialog.Description>{character?.nativeName||character?.role||'Сведения из каталогов'}</Dialog.Description></div><Dialog.Close className="circle-button" aria-label="Закрыть персонажа"><X size={20}/></Dialog.Close></header>
 {character&&<><div className="character-sheet-intro"><div className="character-sheet-portrait">{renderArtwork(character)}</div><div><dl className="character-sheet-facts">{basic.length?basic.map(a=><div key={a.key}><dt>{a.label}</dt><dd title={a.source}>{a.value}</dd></div>):<div><dt>Параметры</dt><dd>{busy?'Загружаем…':'Источник пока не указал'}</dd></div>}</dl>{character.aliases?.length>0&&<p className="entity-aliases">{character.aliases.join(' · ')}</p>}{character.actors?.length>0&&<p className="character-sheet-voices"><small>Сэйю</small>{character.actors.join(', ')}</p>}</div></div>
 <div className="entity-biography">{busy?<p role="status">Загружаем сведения о персонаже…</p>:<p>{character.description||'Описание пока не опубликовано в каталоге.'}</p>}</div>
 {extra.length>0&&<section className="character-spoilers"><button className="text-link" aria-expanded={spoilers} onClick={()=>setSpoilers(v=>!v)}>{spoilers?'Скрыть':'Показать'} сведения с возможными спойлерами · {extra.length}</button>{spoilers&&<dl className="character-sheet-facts">{extra.map(a=><div key={a.key}><dt>{a.label}</dt><dd><span>{a.value}</span><a href={a.url} target="_blank" rel="noopener noreferrer">{a.source}<ExternalLink size={10}/></a></dd></div>)}</dl>}</section>}
 {character.appearances?.length>0&&<section className="character-works"><h3>Появления в произведениях</h3>{character.appearances.map(work=><button key={work.kind+work.id} onClick={()=>{onClose();onRelated?.({...work,ids:{mal:work.id}});}}>{work.kind==='manga'?<BookOpen size={16}/>:<Tv size={16}/>}<span>{work.title}</span><small>{work.role}</small></button>)}</section>}
 <footer className="entity-sources"><a href={browseHref('character','',character.id,character.name)}>Все появления героя<ExternalLink size={13}/></a>{character.sources?.map(s=><a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">{s.name}<ExternalLink size={12}/></a>)}</footer>{error&&<p className="inline-error" role="alert">{error}</p>}</>}
 </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
