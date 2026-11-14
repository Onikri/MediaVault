import {useEffect} from 'react';

// The browser tab names what is open and wears a matching MediaVault mark,
// so several open titles are told apart at a glance.
export const BRAND_TITLE='MediaVault — твои истории рядом';
const KIND_LABELS={anime:'Аниме',manga:'Манга',ranobe:'Ранобэ',book:'Книга',movie:'Фильм',tv:'Сериал',video:'Видео',music:'Музыка'};
const RED='#ee3c35',INK='#0c0c0f';
// Glyphs in the 192px brand tile; the plain brand mark stays the default icon.
const GLYPHS={
 anime:`<path d="M70 52v88l74-44Z" fill="${INK}"/>`,
 video:`<path d="M70 52v88l74-44Z" fill="${INK}"/>`,
 movie:`<rect x="38" y="62" width="116" height="84" rx="10" fill="${INK}"/><path d="M38 62l108-26 4 18-108 26Z" fill="${INK}"/><path d="M62 56l12 14M94 48l12 14M126 41l12 14" stroke="${RED}" stroke-width="8"/>`,
 tv:`<rect x="34" y="54" width="124" height="86" rx="14" fill="${INK}"/><path d="M76 40l20 14 20-14M70 154h52" stroke="${INK}" stroke-width="10" stroke-linecap="round" fill="none"/>`,
 manga:`<path d="M96 60c-16-12-38-16-58-14v92c20-2 42 2 58 14 16-12 38-16 58-14V46c-20-2-42 2-58 14Z" fill="${INK}"/><path d="M96 62v88" stroke="${RED}" stroke-width="7"/>`,
 ranobe:`<path d="M54 40h76a10 10 0 0 1 10 10v104H64a10 10 0 0 1-10-10Z" fill="${INK}"/><path d="M76 72h44M76 92h44M76 112h30" stroke="${RED}" stroke-width="8" stroke-linecap="round"/>`,
 music:`<path d="M80 48l64-14v86" stroke="${INK}" stroke-width="12" fill="none" stroke-linejoin="round"/><circle cx="66" cy="136" r="22" fill="${INK}"/><circle cx="130" cy="122" r="22" fill="${INK}"/><path d="M80 48v88" stroke="${INK}" stroke-width="12"/>`
};
GLYPHS.book=GLYPHS.ranobe;
export const kindLabel=kind=>KIND_LABELS[kind]||'';
export function kindIcon(kind){
 const glyph=GLYPHS[kind];if(!glyph)return null;
 return 'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect width="192" height="192" rx="48" fill="${RED}"/>${glyph}</svg>`);
}
export function tabTitle(title,kind){
 const name=String(title||'').trim(),label=kindLabel(kind);
 if(!name||name==='Загружаем тайтл…')return label?label+' · MediaVault':BRAND_TITLE;
 return name+(label?' — '+label:'')+' · MediaVault';
}

function iconLink(){
 let link=document.querySelector('link[rel="icon"][data-tab-identity]');
 if(!link){
  link=document.createElement('link');link.rel='icon';link.type='image/svg+xml';link.dataset.tabIdentity='';
  document.head.append(link);
 }
 return link;
}

/** Shows `title` of `kind` in the tab while the calling view is mounted. */
export function useTabIdentity(title,kind,enabled=true){
 useEffect(()=>{
  if(!enabled||typeof document==='undefined')return;
  const previous=document.title;document.title=tabTitle(title,kind);
  const href=kindIcon(kind),link=href?iconLink():null;
  // A later, more specific link wins over the static brand icon.
  if(link){link.href=href;document.head.append(link);}
  return()=>{document.title=previous||BRAND_TITLE;link?.remove();};
 },[title,kind,enabled]);
}
