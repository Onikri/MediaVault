import {useEffect,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {X,ExternalLink,BookOpen,Tv,Images} from 'lucide-react';
import {browseHref} from './anime-navigation.js';
import './character-profile.css';

export default function CharacterDialog({character,busy,error,onClose,renderArtwork,onRelated,returnFocusRef,workTitle=''}){
 const [spoilers,setSpoilers]=useState(false);
 useEffect(()=>setSpoilers(false),[character?.id]);

 function openArts(){
  const query=[character.original,...(character.aliases||[]),character.name]
   .find(name=>/^[ -~]+$/.test(String(name||'').trim())&&/[a-z]/i.test(name))||character.original||character.name;
  onClose();
  dispatchEvent(new CustomEvent('mediavault:arts',{detail:{query,title:workTitle}}));
 }

 const attributes=character?.attributes||[];
 const facts=attributes.filter(fact=>!fact.spoiler);
 const spoilerFacts=attributes.filter(fact=>fact.spoiler);
 return <Dialog.Root open={!!character} onOpenChange={open=>{if(!open)onClose();}}>
  <Dialog.Portal>
   <Dialog.Overlay className="dialog-overlay"/>
   <Dialog.Content className="server-dialog character-sheet"
    onCloseAutoFocus={event=>{
     const trigger=returnFocusRef?.current;
     if(trigger?.isConnected){
      event.preventDefault();
      trigger.focus({preventScroll:true});
     }
    }}>
    {character&&<>
     <div className="character-sheet-body">
      <Dialog.Close className="character-sheet-close" aria-label="Закрыть персонажа"><X size={19}/></Dialog.Close>
      <header className="character-sheet-hero">
       <div className="character-sheet-portrait">{renderArtwork(character)}</div>
       <div className="character-sheet-name">
        <Dialog.Title translate="no">{character.name}</Dialog.Title>
        <Dialog.Description translate="no">{character.nativeName||character.role||'Сведения из каталогов'}</Dialog.Description>
        {character.aliases?.length>0&&<p className="character-sheet-aliases" translate="no">{character.aliases.join(' · ')}</p>}
        <button type="button" className="character-arts" onClick={openArts}><Images size={15}/>Посмотреть арты</button>
       </div>
      </header>

      {(facts.length>0||character.actors?.length>0)&&<dl className="character-sheet-facts">
       {facts.map(fact=><div key={fact.key}><dt>{fact.label}</dt><dd title={fact.source}>{fact.value}</dd></div>)}
       {character.actors?.length>0&&<div className="character-sheet-voices"><dt>Сэйю</dt><dd>{character.actors.join(', ')}</dd></div>}
      </dl>}

      <div className="character-sheet-biography" translate="no">
       {busy?<p role="status">Загружаем сведения о персонаже…</p>:<p>{character.description||'Описание пока не опубликовано в каталоге.'}</p>}
      </div>
      {spoilerFacts.length>0&&<section className="character-spoilers">
       <button type="button" className="text-link" aria-expanded={spoilers} onClick={()=>setSpoilers(value=>!value)}>
        {spoilers?'Скрыть':'Показать'} сведения с возможными спойлерами · {spoilerFacts.length}
       </button>
       {spoilers&&<dl className="character-sheet-facts">
        {spoilerFacts.map(fact=><div key={fact.key}><dt>{fact.label}</dt><dd><span>{fact.value}</span>
         <a href={fact.url} target="_blank" rel="noopener noreferrer">{fact.source}<ExternalLink size={10}/></a>
        </dd></div>)}
       </dl>}
      </section>}

      {character.appearances?.length>0&&<section className="character-works">
       <h3>Появления в произведениях</h3>
       <ul>{character.appearances.map(work=><li key={work.kind+work.id}>
        <button type="button" onClick={()=>{onClose();onRelated?.({...work,ids:{mal:work.id}});}}>
         {work.kind==='manga'?<BookOpen size={15}/>:<Tv size={15}/>}
         <span>{work.title}</span><small>{work.role}</small>
        </button>
       </li>)}</ul>
      </section>}

      <footer className="character-sheet-sources">
       <a href={browseHref('character','',character.id,character.name)}>Все появления героя<ExternalLink size={12}/></a>
       {character.sources?.map(source=><a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.name}<ExternalLink size={12}/></a>)}
      </footer>
      {error&&<p className="inline-error" role="alert">{error}</p>}
     </div>
    </>}
   </Dialog.Content>
  </Dialog.Portal>
 </Dialog.Root>;
}
