import {Children,cloneElement,isValidElement,useEffect,useRef,useState} from 'react';
import UiSelect from './UiSelect.jsx';
import UiSwitch from './UiSwitch.jsx';
import {ChevronDown,X} from 'lucide-react';
import PlayerPopover from './PlayerPopover.jsx';

export function SettingsGlyph(){
  return <svg className="settings-glyph" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/><g><circle className="slider-knob knob-top" cx="8" cy="6" r="2.5"/><circle className="slider-knob knob-middle" cx="16" cy="12" r="2.5"/><circle className="slider-knob knob-bottom" cx="15" cy="18" r="2.5"/></g></svg>;
}
// Native selects and checkboxes handed in by callers (online source configuration)
// become the site's own select and switch.
export function themedControls(node){
 if(!isValidElement(node))return node;
 if(node.type==='select')return <UiSelect {...node.props} key={node.key}/>;
 if(node.type==='input'&&node.props.type==='checkbox')return <UiSwitch {...node.props} key={node.key}/>;
 return node.props.children===undefined?node:cloneElement(node,{},Children.map(node.props.children,themedControls));
}

// Where an item sits inside its visual run: an opened item splits its group in two,
// so the neighbours above and below get their own rounded ends.
function runPositions(items,open){
 const runs=[];let run=[];
 items.forEach((item,i)=>{if(item.id===open){if(run.length)runs.push(run);runs.push([i]);run=[];}else run.push(i);});
 if(run.length)runs.push(run);
 const pos={};
 for(const r of runs)r.forEach((index,k)=>{pos[index]=r.length===1?'single':k===0?'first':k===r.length-1?'last':'middle';});
 return pos;
}

function Section({item,position,open,onToggle,close}){
 const body=useRef(null);
 const expandable=!!item.content;
 useEffect(()=>{if(open)setTimeout(()=>body.current?.closest('.mvx-item')?.scrollIntoView({block:'nearest',behavior:'smooth'}),260);},[open]);
 if(item.switch)return <div className="mvx-item" data-pos={position}>
  <button type="button" className="mvx-row mvx-switch-row" role="switch" aria-checked={!!item.switch.checked} onClick={()=>item.switch.onChange(!item.switch.checked)}>
   <span className="mvx-row-text"><span>{item.label}</span>{item.hint&&<small>{item.hint}</small>}</span><span className="mvx-switch" aria-hidden="true"><i/></span>
  </button>
 </div>;
 return <div className={'mvx-item'+(open?' is-open':'')} data-pos={position}>
  <button type="button" className="mvx-row" aria-expanded={expandable?open:undefined} disabled={!expandable&&!item.onClick} onClick={()=>item.onClick?item.onClick():onToggle(item.id)}>
   <span className="mvx-row-text"><span>{item.label}</span>{item.hint&&<small>{item.hint}</small>}</span>
   <span className="mvx-row-value">{item.value}</span>
   {expandable&&<ChevronDown className="mvx-row-chevron" size={16} aria-hidden="true"/>}
  </button>
  {expandable&&<div className="mvx-item-body" aria-hidden={!open} inert={!open}><div ref={body} className="mvx-item-inner">{typeof item.content==='function'?item.content(close):item.content}</div></div>}
 </div>;
}

// One column. Rows sit in groups; opening a row pulls it out of its group like a
// droplet, unfolds its options in place and folds back after a choice.
export default function PlayerSettings({onClose,children,anchor,initialPage,sections,actions,footer}){
  const legacy=!sections&&children;
  const [open,setOpen]=useState(initialPage&&initialPage!=='watch'?initialPage:'');
  useEffect(()=>{setOpen(initialPage&&initialPage!=='watch'?initialPage:'');},[initialPage]);
  // While a block unfolds or folds, scrollbars stay hidden; they fade in once it settles.
  const [settling,setSettling]=useState(false),settleTimer=useRef(0);
  useEffect(()=>{setSettling(true);clearTimeout(settleTimer.current);settleTimer.current=setTimeout(()=>setSettling(false),560);return()=>clearTimeout(settleTimer.current);},[open]);
  const close=()=>setOpen('');
  const toggle=id=>setOpen(old=>old===id?'':id);
  return <PlayerPopover anchor={anchor} label="Настройки просмотра" className="mvx-sheet mvx-settings" onClose={onClose}>
    <div id="player-settings" data-settings-nested={open||undefined}
      onKeyDownCapture={event=>{if(event.key==='Escape'&&open&&!event.target.closest?.('[data-mv-select-content]')){event.preventDefault();event.stopPropagation();const row=event.currentTarget.querySelector('.mvx-item.is-open>.mvx-row');close();row?.focus();}}}>
      <div className={'mvx-sheet-page mvx-scroll'+(settling?' is-settling':'')}>
        {legacy?<div className="mvx-source">{themedControls(children.watch||Object.values(children).find(Boolean))}</div>:<>
          {sections.filter(g=>g.items.some(Boolean)).map(group=>{
            const items=group.items.filter(Boolean),pos=runPositions(items,open);
            return <div className="mvx-group" key={group.id}>{items.map((item,i)=><Section key={item.id} item={item} position={pos[i]} open={open===item.id} onToggle={toggle} close={close}/>)}</div>;
          })}
          {actions}
          {footer}
        </>}
      </div>
    </div>
  </PlayerPopover>;
}
