import {useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {motion,useReducedMotion} from 'motion/react';
import {BookOpen,CalendarDays,Images,ListOrdered,MessageSquare,Music2,Network,Play,Users} from 'lucide-react';
import {publishTitleNavigation,jumpTitleSection} from './title-navigation-store.js';
import './title-capsule.css';
const ICONS={titlePlayback:Play,titleCharacters:Users,titleStills:Images,titleSchedule:CalendarDays,titleMusic:Music2,titleRelated:Network,titleWatchOrder:ListOrdered,titleDiscussion:MessageSquare};
// One registry feeds inline shortcuts, the header menu and scroll tracking.
export function titleSections(title,profile,extra=[]){return [
 ...(title.items?.length||title.online?[{id:'titlePlayback',label:['manga','book'].includes(title.category)?'Читать':'Смотреть'}]:[]),
 {id:'titleCharacters',label:'Персонажи'},
 ...(profile.screenshots?.length?[{id:'titleStills',label:'Кадры'}]:[]),
 ...(title.section==='anime'?[{id:'titleSchedule',label:'Расписание'},{id:'titleMusic',label:'Музыка'}]:[]),
 ...(profile.related?.length?[{id:'titleRelated',label:'Связи'}]:[]),
 ...(title.section==='anime'&&profile.sourceId?[{id:'titleWatchOrder',label:'Порядок просмотра'}]:[]),
 {id:'titleDiscussion',label:'Обсуждение'},...extra];}
export default function TitleNavigation({title,profile,extraSections=[]}){
 const sections=titleSections(title,profile,extraSections),key=sections.map(s=>s.id+':'+s.label).join('|'),root=useRef(null),previous=useRef(null),reduce=useReducedMotion();
 const [state,setState]=useState({active:sections[0]?.id,merged:false,width:144,left:0}),[bridge,setBridge]=useState(null);
 useLayoutEffect(()=>{let frame=0;const update=()=>{frame=0;const brand=document.querySelector('.header-brand-area .brand.logo'),header=document.querySelector('.blossom-navbar'),row=root.current;if(!row)return;const b=brand?.getBoundingClientRect(),h=header?.getBoundingClientRect(),r=row.getBoundingClientRect(),boundary=(h?.bottom||78)+16,merged=!!b&&r.top<=boundary;
  const nodes=sections.map(s=>({s,node:document.getElementById(s.id)||(s.id==='titlePlayback'?document.getElementById('titleMaterials'):null)})).filter(v=>v.node).map(v=>({...v,top:v.node.getBoundingClientRect().top})).sort((a,b)=>a.top-b.top);
  const active=(scrollY>0&&scrollY+innerHeight>=document.documentElement.scrollHeight-2?nodes.at(-1)?.s.id:nodes.filter(v=>v.top<=boundary+40).at(-1)?.s.id)||nodes[0]?.s.id||sections[0]?.id,next={active,merged,width:b?.width||144,left:Math.max(0,(b?.left||r.left)-r.left)};
  if(previous.current&&previous.current.merged!==merged&&b&&!reduce&&Math.abs(r.top-b.top)<180)setBridge({key:performance.now(),left:b.left,top:b.top,width:b.width,from:merged?r.top-b.top:0,to:merged?0:r.top-b.top,label:sections.find(s=>s.id===active)?.label});
  if(!previous.current||Object.keys(next).some(k=>previous.current[k]!==next[k])){previous.current=next;setState(next);publishTitleNavigation({titleId:title.id,sections:sections.map(({id,label})=>({id,label})),active,merged});}
 };const schedule=()=>{if(!frame)frame=requestAnimationFrame(update);};update();const observer=new ResizeObserver(schedule);if(root.current)observer.observe(root.current);const h=document.querySelector('.blossom-navbar');if(h)observer.observe(h);addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule);return()=>{cancelAnimationFrame(frame);observer.disconnect();removeEventListener('scroll',schedule);removeEventListener('resize',schedule);publishTitleNavigation(null);previous.current=null;};},[title.id,key,reduce]);
 return <><div ref={root} className="title-navigation-anchor" style={{paddingLeft:state.left,'--title-capsule-width':state.width+'px'}}><nav className={'title-shortcuts title-capsule-shortcuts title-tabbar'+(state.merged?' is-absorbed':'')} aria-label="Разделы тайтла" aria-hidden={state.merged} inert={state.merged}>{sections.map(s=>{const Glyph=s.id==='titlePlayback'&&s.label==='Читать'?BookOpen:ICONS[s.id];const current=state.active===s.id;return <button type="button" key={s.id} aria-current={current?'location':undefined} onClick={()=>jumpTitleSection(s.id)}>{current&&<motion.span className="title-tab-indicator" layoutId="title-tab-indicator" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}{Glyph&&<Glyph size={16} aria-hidden="true"/>}<span>{s.label}</span></button>;})}</nav></div>{bridge&&createPortal(<motion.div key={bridge.key} className="title-nav-droplet" aria-hidden="true" style={{position:'fixed',left:bridge.left,top:bridge.top,width:bridge.width,height:38}} initial={{y:bridge.from,opacity:1,scaleY:1}} animate={{y:bridge.to,opacity:[1,1,0],scaleY:[1,1.35,1]}} transition={{duration:.48,ease:[.22,.8,.2,1]}} onAnimationComplete={()=>setBridge(null)}>{bridge.label}</motion.div>,document.body)}</>;
}
