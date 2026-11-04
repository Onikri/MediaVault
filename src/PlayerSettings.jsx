import {Children,Fragment,useEffect,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import {SlidersHorizontal,Sparkles,Subtitles,Share2,X,Sun,SkipForward,Users} from 'lucide-react';
import PlayerPopover from './PlayerPopover.jsx';
import {usePlayerSpace} from './player-session.js';

export function SettingsGlyph(){
  return <svg className="settings-glyph" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/><g><circle className="slider-knob knob-top" cx="8" cy="6" r="2.5"/><circle className="slider-knob knob-middle" cx="16" cy="12" r="2.5"/><circle className="slider-knob knob-bottom" cx="15" cy="18" r="2.5"/></g></svg>;
}
const pages=[['watch','Просмотр',SlidersHorizontal],['image','Изображение',Sparkles],['effects','Атмосфера',Sun],['captions','Субтитры',Subtitles],['intro','Пропуск',SkipForward],['actions','Действия',Share2],['room','Комната',Users]];
export default function PlayerSettings({onClose,children,anchor,initialPage='watch'}){
  const height=usePlayerSpace(),available=pages.filter(([id])=>children[id]);
  const [page,setPage]=useState(initialPage),[part,setPart]=useState(0),root=useRef(null),reduced=useReducedMotion();
  useEffect(()=>setPage(initialPage),[initialPage]);
  const flatten=nodes=>Children.toArray(nodes).flatMap(n=>typeof n==='string'||n.props.hidden?[]:n.type===Fragment||['watch-player-configuration','watch-selection','watch-quality-note'].includes(n.props.className)?flatten(n.props.children):n.type==='fieldset'?flatten(n.props.children).filter(c=>c.type!=='legend'):[n]);
  const rows=flatten(children[page]?.props.children),size=height<240?1:height<330?2:4,count=Math.ceil(rows.length/size);
  useEffect(()=>setPart(0),[page]);
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
  return <PlayerPopover anchor={anchor} label="Настройки просмотра" className="mv-player-drawer player-settings-glass" onClose={onClose}><div ref={root} id="player-settings" onKeyDown={keyboard}>
    <div className="player-settings-tabs" style={{gridTemplateColumns:`repeat(${available.length},minmax(0,1fr))`}} role="tablist" aria-label="Разделы настроек">{available.map(([id,label,Icon],index)=><button role="tab" aria-label={label} title={label} key={id} id={'settings-tab-'+id} aria-controls={'settings-page-'+id} aria-selected={page===id} tabIndex={page===id?0:-1} onClick={()=>setPage(id)} onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?available.length-1:(index+(event.key==='ArrowRight'?1:-1)+available.length)%available.length;setPage(available[next][0]);root.current.querySelector('#settings-tab-'+available[next][0])?.focus();}}}><Icon size={17}/></button>)}</div>
    <motion.div key={page+':'+part} initial={{opacity:reduced?1:0,x:reduced?0:5}} animate={{opacity:1,x:0}} transition={{duration:reduced?0:.16,ease:[.2,.8,.2,1]}} role="tabpanel" id={'settings-page-'+page} aria-labelledby={'settings-tab-'+page} className="player-settings-page"><div className="mv-player-settings">{rows.slice(Math.max(0,Math.min(part,count-1))*size,(Math.max(0,Math.min(part,count-1))+1)*size).map((child,i)=><div className="player-setting-row" key={page+':'+part+':'+i}>{child}</div>)}</div></motion.div>
    {count>1&&<nav className="player-page-dots" aria-label="Страницы настроек"><button disabled={part===0} onClick={()=>setPart(n=>n-1)} aria-label="Предыдущие настройки">‹</button>{Array.from({length:count},(_,i)=><button key={i} aria-label={'Страница настроек '+(i+1)} aria-current={part===i?'page':undefined} onClick={()=>setPart(i)}><i/></button>)}<button disabled={part>=count-1} onClick={()=>setPart(n=>n+1)} aria-label="Следующие настройки">›</button></nav>}
  </div></PlayerPopover>;
}
