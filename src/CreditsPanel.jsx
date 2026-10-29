import {useMemo,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {Clapperboard,X,ExternalLink} from 'lucide-react';
import {loadPerson} from './title-metadata.js';
export default function CreditsPanel({profile,server,renderArtwork,kind='anime'}){
  const [expanded,setExpanded]=useState(false),[person,setPerson]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),generation=useRef(0);
  const values=useMemo(()=>{
    const people=[...(profile.staff||[]),...(profile.characters||[]).flatMap(c=>(c.voiceActors||[]).map(v=>({...v,role:'Сэйю · '+c.name})))];
    return [...new Map(people.map(p=>[p.id+':'+p.role,p])).values()];
  },[profile.staff,profile.characters]);
  if(!values.length)return null;
  async function open(value){const current=++generation.current;setPerson(value);setError('');setLoading(true);try{const detail=await loadPerson(value.id,{server});if(current===generation.current)setPerson({...value,...detail});}catch(cause){if(current===generation.current)setError(cause.message);}finally{if(current===generation.current)setLoading(false);}}
  return <section className="title-credits"><div className="section-heading"><h2><Clapperboard size={17}/>{kind==='anime'?'Над аниме работали':'Авторы и художники'}</h2><span className="fine">{kind==='anime'?'Авторы · Художники · Сэйю':'Авторы · Художники'}</span></div><div className="credits-grid">{(expanded?values:values.slice(0,8)).map(value=><button key={value.id+value.role} onClick={()=>open(value)}><span className="credit-portrait">{renderArtwork(value)}</span><span><strong>{value.name}</strong><small>{value.role}</small></span></button>)}</div>{values.length>8&&<button className="text-link credits-expand" onClick={()=>setExpanded(v=>!v)}>{expanded?'Свернуть':(kind==='anime'?'Вся съёмочная группа · ':'Все участники · ')+values.length}</button>}
    <Dialog.Root open={!!person} onOpenChange={value=>{if(!value){generation.current++;setPerson(null);}}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog person-dialog"><Dialog.Close className="icon-button dialog-close" aria-label="Закрыть участника группы"><X size={18}/></Dialog.Close><Dialog.Title>{person?.name}</Dialog.Title><Dialog.Description>{person?.role}</Dialog.Description>{person&&<><span className="person-portrait">{renderArtwork(person)}</span><p>{loading?'Загружаем сведения…':person.description||'Русская биография пока не опубликована в каталоге.'}</p>{error&&<p className="inline-error">{error}</p>}<a className="text-link" href={'https://shikimori.io/people/'+person.id} target="_blank" rel="noopener noreferrer">Страница в каталоге<ExternalLink size={13}/></a></>}</Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>;
}
