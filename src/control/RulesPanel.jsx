import {useEffect,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Minus,Plus} from 'lucide-react';
import UiSwitch from '../UiSwitch.jsx';
import UiSelect from '../UiSelect.jsx';

const TERMS=[['1','1 день'],['7','7 дней'],['30','30 дней'],['90','3 месяца'],['365','Год'],['0','Без срока']];

function Stepper({id,value,min,max,unit,onChange}){
 const set=v=>onChange(Math.min(max,Math.max(min,Math.round(Number(v)||min))));
 return <div className="cc-stepper">
  <button type="button" aria-label="Меньше" disabled={value<=min} onClick={()=>set(value-1)}><Minus size={15}/></button>
  <input id={id} inputMode="numeric" value={value} onChange={e=>set(e.target.value.replace(/\D/g,''))} aria-describedby={id+'-range'}/>
  <button type="button" aria-label="Больше" disabled={value>=max} onClick={()=>set(value+1)}><Plus size={15}/></button>
  <span id={id+'-range'} className="cc-stepper-unit">{unit}</span>
 </div>;
}

function Rule({label,hint,children,changed}){
 return <div className={'cc-rule'+(changed?' is-changed':'')}><div className="cc-rule-text"><span className="cc-rule-label">{label}</span>{hint&&<span className="cc-hint">{hint}</span>}</div><div className="cc-rule-control">{children}</div></div>;
}

export default function RulesPanel({service,onSaved}){
 const reduce=useReducedMotion();
 const [saved,setSaved]=useState(null),[draft,setDraft]=useState(null),[defaults,setDefaults]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[done,setDone]=useState(false);
 useEffect(()=>{service.request('/admin/rules').then(v=>{setSaved(v.rules);setDraft(v.rules);setDefaults(v.defaults);}).catch(e=>setError(e.status===404?'Сервер ещё не умеет хранить правила. Обнови MediaVault на ВМ.':e.message));},[service.request]);
 if(!draft)return error?<p className="cc-error" role="alert">{error}</p>:<p className="cc-hint">Загружаем правила…</p>;
 const set=(section,key)=>value=>{setDone(false);setDraft(d=>({...d,[section]:{...d[section],[key]:value}}));};
 const diff=(section,key)=>saved[section][key]!==draft[section][key];
 const dirty=JSON.stringify(saved)!==JSON.stringify(draft),isDefault=defaults&&JSON.stringify(defaults)===JSON.stringify(draft);
 async function save(){setBusy(true);setError('');try{const v=await service.request('/admin/rules',{method:'PUT',body:draft});setSaved(v.rules);setDraft(v.rules);setDone(true);onSaved?.();}catch(e){setError(e.message);}finally{setBusy(false);}}
 const r=draft.rooms,g=draft.guests;
 return <div className="cc-rules">
  <section aria-labelledby="cc-rules-rooms">
   <div className="cc-section-head"><h2 id="cc-rules-rooms">Комнаты совместного просмотра</h2></div>
   <div className="cc-rule-list">
    <Rule label="Комнат на сервере" hint="Сколько комнат может быть открыто одновременно" changed={diff('rooms','limit')}><Stepper id="rule-limit" value={r.limit} min={1} max={64} unit="из 64" onChange={set('rooms','limit')}/></Rule>
    <Rule label="Комнат у одного ведущего" hint="Старые пустые комнаты ведущего закрываются сами" changed={diff('rooms','perOwner')}><Stepper id="rule-owner" value={r.perOwner} min={1} max={8} unit="из 8" onChange={set('rooms','perOwner')}/></Rule>
    <Rule label="Мест в комнате" hint="Без учёта ведущего" changed={diff('rooms','members')}><Stepper id="rule-members" value={r.members} min={1} max={16} unit="из 16" onChange={set('rooms','members')}/></Rule>
    <Rule label="Сколько живёт ссылка" hint="Действует для новых комнат" changed={diff('rooms','hours')}><Stepper id="rule-hours" value={r.hours} min={1} max={48} unit="часов" onChange={set('rooms','hours')}/></Rule>
    <Rule label="Гости могут открывать комнаты" hint="Иначе комнату открываешь только ты" changed={diff('rooms','guestsMayHost')}><UiSwitch checked={r.guestsMayHost} onCheckedChange={set('rooms','guestsMayHost')} aria-label="Гости могут открывать комнаты"/></Rule>
   </div>
  </section>
  <section aria-labelledby="cc-rules-guests">
   <div className="cc-section-head"><h2 id="cc-rules-guests">Новые гости</h2><span className="cc-hint">Уже созданных гостей не меняет</span></div>
   <div className="cc-rule-list">
    <Rule label="Срок доступа по умолчанию" hint="Подставляется в форму приглашения" changed={diff('guests','days')}><UiSelect aria-label="Срок доступа по умолчанию" value={String(g.days)} onChange={e=>set('guests','days')(Number(e.target.value))}>{TERMS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</UiSelect></Rule>
    <Rule label="Можно смотреть" hint="Аниме, фильмы и сериалы" changed={diff('guests','watch')}><UiSwitch checked={g.watch} onCheckedChange={set('guests','watch')} aria-label="Новым гостям можно смотреть"/></Rule>
    <Rule label="Можно читать" hint="Манга и ранобэ" changed={diff('guests','read')}><UiSwitch checked={g.read} onCheckedChange={set('guests','read')} aria-label="Новым гостям можно читать"/></Rule>
   </div>
  </section>
  {error&&<p className="cc-error" role="alert">{error}</p>}
  <AnimatePresence>{(dirty||done)&&<motion.div className="cc-savebar" role="status" initial={reduce?false:{opacity:0,y:16}} animate={{opacity:1,y:0}} exit={reduce?{opacity:0}:{opacity:0,y:16}} transition={{type:'spring',stiffness:420,damping:34}}>
   <span>{dirty?'Правила изменены, но ещё не сохранены':'Правила сохранены и уже действуют'}</span>
   {dirty&&<><button type="button" className="cc-button" disabled={busy} onClick={()=>setDraft(saved)}>Отменить</button><button type="button" className="btn btn-primary" disabled={busy} onClick={save}>{busy?'Сохраняем…':'Сохранить правила'}</button></>}
  </motion.div>}</AnimatePresence>
  {!isDefault&&defaults&&<button type="button" className="cc-text-button cc-reset" onClick={()=>{setDone(false);setDraft(defaults);}}>Вернуть стандартные правила</button>}
 </div>;
}
