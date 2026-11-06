import {useLayoutEffect,useRef,useState} from 'react';

// A real <input> keeps focus, IME, autofill and password managers; its own
// glyphs are transparent and a mirror draws them instead, so every typed
// character can arrive with its own small motion. Characters keep stable ids
// across edits, so only what was actually inserted animates.
function useCharacterIds(value){
 const model=useRef({value:'',ids:[],next:0}),m=model.current;
 if(m.value!==value){
  const a=m.value,b=value;let p=0,s=0;
  while(p<a.length&&p<b.length&&a[p]===b[p])p++;
  while(s<a.length-p&&s<b.length-p&&a[a.length-1-s]===b[b.length-1-s])s++;
  m.ids=[...m.ids.slice(0,p),...Array.from({length:b.length-p-s},()=>m.next++),...m.ids.slice(a.length-s)];m.value=b;
 }
 return m.ids;
}

export default function TypingField({value,onChange,secret=false,reveal=false,className='',...props}){
 const input=useRef(null),view=useRef(null),track=useRef(null),offset=useRef(0);
 const [selection,setSelection]=useState([value.length,value.length]),[focused,setFocused]=useState(false);
 const ids=useCharacterIds(value),masked=secret&&!reveal;
 const sync=()=>{const el=input.current;if(el)setSelection([el.selectionStart??el.value.length,el.selectionEnd??el.value.length]);};
 const [start,end]=selection,collapsed=start===end;
 // Keep the caret in view when the text is wider than the field.
 useLayoutEffect(()=>{
  const box=view.current,line=track.current;if(!box||!line)return;
  const mark=line.querySelector('[data-caret]')||line.children[Math.min(start,line.children.length-1)];
  const x=mark?mark.offsetLeft+(mark.dataset.caret!=null?0:start>=line.children.length?mark.offsetWidth:0):0,width=box.clientWidth-28;
  if(x-offset.current>width)offset.current=x-width;else if(x<offset.current)offset.current=Math.max(0,x-8);
  if(line.scrollWidth<=width)offset.current=0;line.style.transform=`translateX(${-offset.current}px)`;
 });
 const characters=[];
 for(let i=0;i<=value.length;i++){
  if(i===start&&collapsed&&focused)characters.push(<span key={'caret'+value.length+':'+start} className="tf-caret" data-caret="" aria-hidden="true"/>);
  if(i===value.length)break;
  const chosen=i>=start&&i<end&&!collapsed;
  characters.push(masked
   ?<span key={ids[i]+'h'} className={'tf-char tf-dot'+(chosen?' is-selected':'')} style={{'--i':i}}/>
   :<span key={ids[i]+(secret?'r':'')} className={'tf-char'+(chosen?' is-selected':'')} style={{'--i':i}}>{value[i]===' '?' ':value[i]}</span>);
 }
 return <span ref={view} className={'tf'+(focused?' is-focused':'')+(reveal?' is-revealed':'')+(className?' '+className:'')}>
  <input ref={input} {...props} type={masked?'password':'text'} value={value} spellCheck={false}
   onChange={e=>{onChange(e);requestAnimationFrame(sync);}} onSelect={sync} onKeyUp={sync}
   onFocus={e=>{setFocused(true);sync();props.onFocus?.(e);}} onBlur={e=>{setFocused(false);props.onBlur?.(e);}}/>
  <span className="tf-mirror" aria-hidden="true"><span ref={track} className="tf-track">{characters}</span></span>
 </span>;
}
