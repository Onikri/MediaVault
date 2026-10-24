import {useEffect,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import {SlidersHorizontal,Sparkles,Subtitles,Share2,X} from 'lucide-react';

export function SettingsGlyph(){
  return <svg className="settings-glyph" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/><g><circle className="slider-knob knob-top" cx="8" cy="6" r="2.5"/><circle className="slider-knob knob-middle" cx="16" cy="12" r="2.5"/><circle className="slider-knob knob-bottom" cx="15" cy="18" r="2.5"/></g></svg>;
}
const pages=[['watch','Просмотр',SlidersHorizontal],['image','Изображение',Sparkles],['captions','Субтитры',Subtitles],['actions','Действия',Share2]];
export default function PlayerSettings({onClose,children}){
  const [page,setPage]=useState('watch'),root=useRef(null),reduced=useReducedMotion();
  useEffect(()=>{
    const previous=document.activeElement;root.current?.querySelector('[role=tab][aria-selected=true]')?.focus({preventScroll:true});
    return()=>previous?.isConnected&&previous.focus({preventScroll:true});
  },[]);
  function keyboard(event){
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();return;}
    if(event.key==='Tab'){
      const nodes=[...root.current.querySelectorAll('button:not(:disabled),select:not(:disabled),input:not(:disabled),a[href]')].filter(n=>n.getClientRects().length);
      const first=nodes[0],last=nodes.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  }
  return <><div className="player-settings-scrim" aria-hidden="true" onPointerDown={onClose}/><motion.section ref={root} initial={{opacity:0,y:reduced?0:9,scale:reduced?1:.97}} animate={{opacity:1,y:0,scale:1}} exit={{opacity:0,y:reduced?0:5,scale:reduced?1:.985}} transition={{duration:reduced?0:.22,ease:[.2,.8,.2,1]}} id="player-settings" role="dialog" aria-label="Настройки просмотра" aria-modal="true" className="mv-player-drawer" onKeyDown={keyboard}>
    <header className="mv-player-drawer-head"><h2>Настройки</h2><button aria-label="Закрыть настройки" onClick={onClose}><X size={17}/></button></header>
    <div className="player-settings-tabs" role="tablist" aria-label="Разделы настроек">{pages.map(([id,label,Icon],index)=><button role="tab" key={id} id={'settings-tab-'+id} aria-controls={'settings-page-'+id} aria-selected={page===id} tabIndex={page===id?0:-1} onClick={()=>setPage(id)} onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?pages.length-1:(index+(event.key==='ArrowRight'?1:-1)+pages.length)%pages.length;setPage(pages[next][0]);root.current.querySelector('#settings-tab-'+pages[next][0])?.focus();}}}><Icon size={17}/><span>{label}</span></button>)}</div>
    {pages.map(([id])=><div role="tabpanel" id={'settings-page-'+id} aria-labelledby={'settings-tab-'+id} key={id} hidden={page!==id} className="player-settings-page">{children[id]}</div>)}
    <footer className="player-settings-shortcuts"><span><kbd>Пробел</kbd> пауза</span><span><kbd>←</kbd><kbd>→</kbd> 10 сек.</span><span><kbd>F</kbd> экран</span></footer>
  </motion.section></>;
}
