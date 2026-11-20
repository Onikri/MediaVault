import {useImperativeHandle,useLayoutEffect,useRef} from 'react';
import './section-navigation.css';

export function NavigationRail({as:Rail='nav',count,className='',variant='sections',style,ref,...props}){
 const rail=useRef(null),previous=useRef(null);
 useImperativeHandle(ref,()=>rail.current,[]);
 useLayoutEffect(()=>{
  const node=rail.current;
  const active=node.querySelector('[aria-current],[aria-pressed="true"],[data-state="active"]');
  if(active===previous.current)return;
  previous.current=active;
  if(!active||node.scrollWidth<=node.clientWidth)return;
  const outer=node.getBoundingClientRect(),item=active.getBoundingClientRect();
  if(item.left<outer.left||item.right>outer.right)
   node.scrollLeft+=item.left+item.width/2-outer.left-outer.width/2;
 });
 return <Rail {...props} ref={rail} className={`mv-nav-rail ${className}`.trim()} data-rail={variant}
  style={{...style,'--nav-count':count}}/>;
}

export function NavigationItem({as:Item='button',className='',icon,label,detail,...props}){
 return <Item type="button" {...props} className={`mv-nav-item ${className}`.trim()}>
  {icon&&<span className="mv-nav-icon" aria-hidden="true">{icon}</span>}
  <span className="mv-nav-label">{label}</span>
  {detail!=null&&<span className="mv-nav-detail">{detail}</span>}
 </Item>;
}
