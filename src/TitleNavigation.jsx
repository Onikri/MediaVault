import {useLayoutEffect,useRef} from 'react';
import {BookOpen,CalendarDays,Images,ListOrdered,Music2,Network,Play,Users} from 'lucide-react';
import {publishTitleNavigation,titleSectionTarget,titleDockBoundary,TITLE_SECTION_JUMP} from './title-navigation-store.js';

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

 useLayoutEffect(()=>{
  const items=JSON.parse(signature);
  const header=document.querySelector('.kt-nav-inner');
  let frame=0,previous,preferred;
  const rememberJump=event=>{preferred=event.detail;schedule();};
  const observer=new ResizeObserver(schedule);
  function schedule(){if(!frame)frame=requestAnimationFrame(update);}
  function update(){
   frame=0;
   if(!anchor.current)return;
   const boundary=titleDockBoundary();
   const nodes=items.flatMap(item=>{
    const node=titleSectionTarget(item.id);
    return node?.getClientRects().length?[{item,top:node.getBoundingClientRect().top}]:[];
   }).sort((a,b)=>a.top-b.top);
   const sections=nodes.map(node=>node.item);
   const keys=sections.map(item=>item.id).join('|');
   const bottom=scrollY>0&&scrollY+innerHeight>=document.documentElement.scrollHeight-2;
   const natural=(bottom?nodes.at(-1):nodes.findLast(node=>node.top<=boundary+18))||nodes[0];
   const chosen=preferred&&nodes.find(node=>node.item.id===preferred);
   // A jump can share its vertical position with a section in the other column.
   const onSameRow=chosen&&Math.abs(chosen.top-natural.top)<=18;
   const visibleAtEnd=chosen&&bottom&&chosen.top>=boundary-2&&chosen.top<innerHeight;
   const active=(onSameRow||visibleAtEnd?chosen:natural)?.item.id;
   if(previous?.active===active&&previous?.keys===keys)return;
   previous={active,keys};
   publishTitleNavigation({titleId:title.id,sections,active});
  }
  update();
  if(header)observer.observe(header);
  const content=anchor.current.closest('.title-page')||anchor.current.parentElement;
  if(content)observer.observe(content);
  addEventListener('scroll',schedule,{passive:true});
  addEventListener('resize',schedule);
  addEventListener(TITLE_SECTION_JUMP,rememberJump);
  return()=>{
   cancelAnimationFrame(frame);
   observer.disconnect();
   removeEventListener('scroll',schedule);
   removeEventListener('resize',schedule);
   removeEventListener(TITLE_SECTION_JUMP,rememberJump);
   publishTitleNavigation(null);
  };
 },[title.id,signature]);

 return <span ref={anchor} className="title-navigation-anchor" hidden/>;
}
