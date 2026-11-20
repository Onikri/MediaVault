import {useLayoutEffect,useRef,useState} from 'react';
import {BookOpen,CalendarDays,Images,ListOrdered,Music2,Network,Play,Users} from 'lucide-react';
import {NavigationItem,NavigationRail} from './SectionNavigation.jsx';
import {jumpTitleSection,publishTitleNavigation} from './title-navigation-store.js';
import './title-capsule.css';

const icons={titlePlayback:Play,titleCharacters:Users,titleStills:Images,titleSchedule:CalendarDays,titleMusic:Music2,titleRelated:Network,titleWatchOrder:ListOrdered};

function titleSections(title,profile){
 return [
  ...(title.items?.length||title.online?[{id:'titlePlayback',label:['manga','book'].includes(title.category)?'Читать':'Смотреть'}]:[]),
  ...(profile.characters?.length?[{id:'titleCharacters',label:['movie','tv'].includes(title.section)?'В ролях':'Персонажи'}]:[]),
  ...(profile.screenshots?.length?[{id:'titleStills',label:'Кадры'}]:[]),
  ...(title.section==='anime'?[{id:'titleSchedule',label:'Расписание'},{id:'titleMusic',label:'Музыка'}]:[]),
  ...(profile.related?.length?[{id:'titleRelated',label:'Связи'}]:[]),
  ...(title.section==='anime'&&profile.sourceId?[{id:'titleWatchOrder',label:'Порядок просмотра'}]:[])
 ];
}

export function TitleSectionIcon({id,label}){
 const Icon=id==='titlePlayback'&&label==='Читать'?BookOpen:icons[id];
 return <Icon aria-hidden="true"/>;
}

export default function TitleNavigation({title,profile}){
 const signature=JSON.stringify(titleSections(title,profile));
 const anchor=useRef(null);
 const [state,setState]=useState({sections:[],active:null,merged:false,keys:''});

 useLayoutEffect(()=>{
  const items=JSON.parse(signature);
  const header=document.querySelector('.blossom-navbar');
  let frame=0,previous;
  const observer=new ResizeObserver(schedule);
  function schedule(){if(!frame)frame=requestAnimationFrame(update);}
  function update(){
   frame=0;
   if(!anchor.current)return;
   const boundary=(header?.getBoundingClientRect().bottom||78)+16;
   const nodes=items.flatMap(item=>{
    const node=document.getElementById(item.id)||(item.id==='titlePlayback'?document.getElementById('titleMaterials'):null);
    return node?.getClientRects().length?[{id:item.id,top:node.getBoundingClientRect().top}]:[];
   }).sort((a,b)=>a.top-b.top);
   const sections=items.filter(item=>nodes.some(node=>node.id===item.id));
   const keys=sections.map(item=>item.id).join('|');
   const merged=sections.length>1&&!!header&&anchor.current.getBoundingClientRect().top<=boundary;
   const bottom=scrollY>0&&scrollY+innerHeight>=document.documentElement.scrollHeight-2;
   const active=(bottom?nodes.at(-1)?.id:nodes.findLast(node=>node.top<=boundary+40)?.id)||nodes[0]?.id;
   if(previous?.active===active&&previous.merged===merged&&previous.keys===keys)return;
   previous={sections,active,merged,keys};
   setState(previous);
   publishTitleNavigation({titleId:title.id,sections,active,merged});
  }
  update();
  observer.observe(anchor.current);
  if(header)observer.observe(header);
  const content=anchor.current.closest('.title-page')||anchor.current.parentElement;
  if(content)observer.observe(content);
  addEventListener('scroll',schedule,{passive:true});
  addEventListener('resize',schedule);
  return()=>{
   cancelAnimationFrame(frame);
   observer.disconnect();
   removeEventListener('scroll',schedule);
   removeEventListener('resize',schedule);
   publishTitleNavigation(null);
  };
 },[title.id,signature]);

 const {sections}=state;
 return <div ref={anchor} className="title-navigation-anchor" hidden={sections.length<2}>
  <NavigationRail className={`title-shortcuts title-tabbar ${state.merged?'is-absorbed':''}`} count={sections.length}
   data-scroll={sections.length>3} aria-label="Разделы тайтла" aria-hidden={state.merged} inert={state.merged}>
   {sections.map(section=><NavigationItem key={section.id}
    aria-current={state.active===section.id?'location':undefined} icon={<TitleSectionIcon {...section}/>} label={section.label}
    onClick={()=>jumpTitleSection(section.id)}/>)}
  </NavigationRail>
 </div>;
}
