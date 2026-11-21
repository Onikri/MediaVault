import {LayoutGroup,motion,useReducedMotion} from 'motion/react';
import {useTitleNavigation,jumpTitleSection} from './title-navigation-store.js';
import {TitleSectionIcon} from './TitleNavigation.jsx';
import './title-section-dock.css';

const spring={type:'spring',stiffness:390,damping:34};

export default function TitleSectionDock({hidden=false}){
 const title=useTitleNavigation();
 const reduced=useReducedMotion();
 if(!title||title.sections.length<2)return null;

 return <nav className="title-dock" aria-label="Разделы тайтла" hidden={hidden}>
  <LayoutGroup id={title.titleId}>
   {title.sections.map(section=>{
    const selected=section.id===title.active;
    return <button type="button" key={section.id} className="title-dock-section"
     aria-label={section.label} aria-current={selected?'location':undefined}
     onClick={()=>jumpTitleSection(section.id)}>
     {selected&&<motion.span className="title-dock-marker" layoutId={reduced?undefined:'active-section'}
      transition={spring} aria-hidden="true"/>}
     <span className="title-dock-icon"><TitleSectionIcon {...section}/></span>
     <span className="title-dock-label" aria-hidden="true">{section.label}</span>
    </button>;
   })}
  </LayoutGroup>
 </nav>;
}
