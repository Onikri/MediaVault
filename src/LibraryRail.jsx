import {useEffect,useState} from 'react';
import {AnimatePresence,LayoutGroup,motion,useReducedMotion} from 'motion/react';
import './library-rail.css';

// «Рельс»: library and collection sections as a chapter rail on the left,
// the chosen section as the page headline, content on the right.
const EASE=[.22,1,.36,1],SPRING={type:'spring',stiffness:520,damping:40,mass:.8};

/** Letters fall in one by one whenever the text changes; words never break apart. */
export function KineticText({text,className=''}){
 const reduced=useReducedMotion(),words=String(text).split(' ');
 return <span className={'mv-kinetic '+className} aria-label={text}>
  <AnimatePresence mode="popLayout" initial={false}>
   <motion.span key={text} className="mv-kinetic-line" aria-hidden="true">
    {words.map((word,w)=>{const base=words.slice(0,w).join(' ').length+(w?1:0);
     return <span key={w}>{w>0&&' '}<span className="mv-kinetic-word">{[...word].map((ch,j)=><motion.span key={j} className="mv-kinetic-ch"
      initial={reduced?{opacity:0}:{y:'0.9em',opacity:0,rotateX:-70,filter:'blur(6px)'}}
      animate={{y:0,opacity:1,rotateX:0,filter:'blur(0px)',transition:{delay:(base+j)*.028,duration:.55,ease:EASE},transitionEnd:{filter:'none'}}}
      exit={reduced?{opacity:0}:{y:'-0.6em',opacity:0,filter:'blur(6px)',transition:{delay:(base+j)*.012,duration:.22}}}>{ch}</motion.span>)}</span></span>;})}
   </motion.span>
  </AnimatePresence>
 </span>;
}

/** Digits roll to their new value. */
export function RollingNumber({value}){
 const digits=String(value).split('');
 return <span className="mv-roll" aria-label={String(value)}>{digits.map((d,i)=><span key={digits.length-i} className="mv-roll-col" aria-hidden="true">
  {/\d/.test(d)?<motion.span className="mv-roll-strip" initial={false} animate={{y:-Number(d)+'em'}} transition={{type:'spring',stiffness:260,damping:32}}>{'0123456789'.split('').map(n=><span key={n}>{n}</span>)}</motion.span>:<span>{d}</span>}
 </span>)}</span>;
}

/**
 * sections: [{id,label,count?,ariaLabel?}] · actions: [{id,label,icon,onClick}]
 * Buttons keep the accessible names of the previous rails («Раздел Манга»).
 */
export function LibraryRail({railRef,className='',label,kicker,note,sections,active,onPick,actions=[],activeAction,layoutId='library-rail'}){
 return <LayoutGroup id={layoutId}><nav ref={railRef} className={'mv-rail '+className} aria-label={label}>
  <span className="mv-rail-kicker">{kicker}</span>
  {note&&<span className="mv-rail-note">{note}</span>}
  <ul className="mv-rail-list">{sections.map(s=>{const on=s.id===active&&!activeAction;return <li key={s.id}>
   <button type="button" className={on?'is-on':undefined} aria-current={on?'page':undefined} aria-label={s.ariaLabel} onClick={()=>onPick(s.id)}>
    {on&&<motion.span layoutId="ink" className="mv-rail-ink" transition={SPRING}/>}
    <span className="mv-rail-label">{s.label}</span>{s.count!=null&&<span className="mv-rail-count">{s.count||'—'}</span>}
   </button></li>;})}</ul>
  {actions.length>0&&<div className="mv-rail-actions" role="group" aria-label="Действия">{actions.map(a=>{const on=a.on??a.id===activeAction;return <button key={a.id} type="button" className={on?'is-on':undefined} aria-pressed={on} aria-label={a.label} title={a.title} disabled={a.disabled} onClick={a.onClick}>
   {on&&<motion.span layoutId="ink" className="mv-rail-ink is-action" transition={SPRING}/>}
   <span className="mv-rail-icon" aria-hidden="true">{a.icon}</span><span className="mv-rail-label">{a.label}</span>
  </button>;})}</div>}
 </nav></LayoutGroup>;
}

/** The chosen section as a kinetic headline, with its count when it is known. */
export function RailHeader({title,count,countLabel='в разделе',kicker='Раздел'}){
 return <header className="mv-rail-head">
  <span className="mv-rail-kicker">{kicker}</span>
  {/* Visual only: the rail's aria-current and the page h1 already name the section. */}
  <div className="mv-rail-title" aria-hidden="true"><KineticText text={title}/></div>
  {count!=null&&<span className="mv-rail-total"><RollingNumber value={count}/><small>{countLabel}</small></span>}
 </header>;
}

/** A soft glow in the colour of the hovered cover, behind the whole page. */
export function CardAmbient(){
 const [tone,setTone]=useState(null);
 useEffect(()=>{const on=event=>setTone(event.detail||null);addEventListener('mediavault:card-tone',on);return()=>removeEventListener('mediavault:card-tone',on);},[]);
 return <div className={'card-ambient'+(tone?' is-on':'')} aria-hidden="true"><span style={tone?{backgroundColor:tone}:undefined}/></div>;
}

export function RailLayout({rail,children,className=''}){
 return <div className={'mv-railed '+className}><CardAmbient/>{rail}<div className="mv-railed-main">{children}</div></div>;
}
