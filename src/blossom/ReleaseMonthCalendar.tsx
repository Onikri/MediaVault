import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {DayPicker} from 'react-day-picker';
import {ru} from 'react-day-picker/locale';
import UiSelect from '../UiSelect.jsx';
import 'react-day-picker/style.css';
import './release-month-calendar.css';
const dateKey=(date:Date)=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
function Dropdown({options=[],...props}:any){return <UiSelect {...props}>{options.map((option:any)=><option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}</UiSelect>;}
const components={Dropdown};
export default function ReleaseMonthCalendar({entries,renderEntry}:{entries:any[];renderEntry:(entry:any)=>any}){
 const root=useRef<HTMLDivElement>(null),[count,setCount]=useState(1),[month,setMonth]=useState<Date>(),[hint,setHint]=useState<any>(null),reduce=useReducedMotion();
 const dates=entries.map(item=>new Date(item.date.slice(0,10)+'T12:00:00')),first=dates[0],last=dates.at(-1),current=month||first;
 useEffect(()=>{const node=root.current;if(!node)return;const observer=new ResizeObserver(()=>setCount(node.clientWidth>=600?2:1));observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>{const close=()=>setHint(null);addEventListener('scroll',close,true);addEventListener('resize',close);return()=>{removeEventListener('scroll',close,true);removeEventListener('resize',close);};},[]);
 if(!first)return null;
 function show(day:Date,event:any){const values=entries.filter(item=>item.date.slice(0,10)===dateKey(day));if(!values.length){setHint(null);return;}const r=event.currentTarget.getBoundingClientRect();setHint({day,values,left:Math.min(innerWidth-Math.min(320,innerWidth-24)-12,Math.max(12,r.left-100)),top:r.bottom+10,above:r.bottom>innerHeight-180});}
 return <div ref={root} className="release-month-calendar"><div className="release-season-picker" role="group" aria-label="Сезон календаря">{['Зима','Весна','Лето','Осень'].map((label,index)=><button key={label} type="button" aria-pressed={Math.floor(current.getMonth()/3)===index} onClick={()=>{setHint(null);setMonth(new Date(current.getFullYear(),index*3,1,12));}}>{label}</button>)}</div>
 <DayPicker locale={ru} weekStartsOn={1} animate={!reduce} captionLayout="dropdown" navLayout="around" components={components} month={current} onMonthChange={value=>{setHint(null);setMonth(value);}} numberOfMonths={count} fixedWeeks startMonth={new Date(first.getFullYear(),0,1)} endMonth={new Date(last!.getFullYear(),11,1)} modifiers={{release:dates}} modifiersClassNames={{release:'has-release'}} showOutsideDays={false} labels={{labelNext:()=> 'Следующий месяц',labelPrevious:()=> 'Предыдущий месяц',labelMonthDropdown:()=> 'Месяц календаря',labelYearDropdown:()=> 'Год календаря'}} onDayMouseEnter={(day,_,event)=>show(day,event)} onDayMouseLeave={()=>setHint(null)} onDayFocus={(day,_,event)=>show(day,event)} onDayBlur={()=>setHint(null)} onDayClick={(day,_,event)=>show(day,event)}/>
 {createPortal(<AnimatePresence>{hint&&<motion.aside key={dateKey(hint.day)} role="tooltip" className="release-date-tooltip" style={{left:hint.left,...(hint.above?{bottom:Math.max(12,innerHeight-hint.top+44)}:{top:hint.top})}} initial={{opacity:0,y:reduce?0:5,scale:reduce?1:.98}} animate={{opacity:1,y:0,scale:1}} exit={{opacity:0}} transition={{type:'spring',stiffness:410,damping:33}}><strong>{hint.day.toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'})}</strong><ul>{hint.values.map((value:any)=><li key={value.episode}>{renderEntry(value)}</li>)}</ul></motion.aside>}</AnimatePresence>,document.body)}
 </div>;
}
