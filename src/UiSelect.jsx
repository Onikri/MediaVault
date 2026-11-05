import {Children,Fragment,isValidElement,useContext,useId,useLayoutEffect,useRef,useState} from 'react';
import * as Select from '@radix-ui/react-select';
import {Check,ChevronDown,ChevronUp} from 'lucide-react';
import {PlayerContext} from './player-session.js';
import './ui-controls.css';
const empty='__mv_empty_option__';
function options(children){return Children.toArray(children).flatMap(node=>!isValidElement(node)?[]:node.type===Fragment||node.type==='optgroup'?options(node.props.children):node.type==='option'?[node]:[]);}
export default function UiSelect({children,value,defaultValue,onChange,onValueChange,disabled,id,className='',name,required,...props}){
 const rows=options(children),autoId=useId(),ref=useRef(null),player=useContext(PlayerContext),[container,setContainer]=useState(null);
 useLayoutEffect(()=>{setContainer(player?.root||ref.current?.closest('[role="dialog"]')||document.fullscreenElement||document.body);},[player]);
 const encode=v=>String(v)===''?empty:String(v),decode=v=>v===empty?'':v;
 const selected=value===undefined?undefined:encode(value);
 return <Select.Root value={selected} defaultValue={defaultValue===undefined?selected===undefined&&rows.length?encode(rows[0].props.value):undefined:encode(defaultValue)} name={name} required={required} disabled={disabled} onOpenChange={open=>{if(open)setContainer(player?.root||ref.current?.closest('[role="dialog"]')||document.fullscreenElement||document.body);}} onValueChange={v=>{const next=decode(v);onValueChange?.(next);onChange?.({target:{value:next},currentTarget:{value:next}});}}>
 <Select.Trigger {...props} id={id||autoId} ref={ref} className={'mv-select-trigger '+className}><Select.Value/><Select.Icon><ChevronDown size={13}/></Select.Icon></Select.Trigger>
 <Select.Portal container={container}><Select.Content onEscapeKeyDown={event=>event.stopPropagation()} position="popper" sideOffset={6} collisionPadding={8} collisionBoundary={player?.root||(container!==document.body?container:undefined)} className="mv-select-content" data-mv-select-content><Select.ScrollUpButton className="mv-select-scroll"><ChevronUp size={13}/></Select.ScrollUpButton><Select.Viewport>{rows.map((row,index)=>{const text=Children.toArray(row.props.children).filter(v=>typeof v==='string'||typeof v==='number').join('');return <Select.Item key={String(row.props.value)+':'+index} value={encode(row.props.value)} disabled={row.props.disabled} textValue={text} className="mv-select-item"><Select.ItemText>{row.props.children}</Select.ItemText><Select.ItemIndicator><Check size={13}/></Select.ItemIndicator></Select.Item>;})}</Select.Viewport><Select.ScrollDownButton className="mv-select-scroll"><ChevronDown size={13}/></Select.ScrollDownButton></Select.Content></Select.Portal>
 </Select.Root>;
}
