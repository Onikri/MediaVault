import ImportQueue from '../ImportQueue.jsx';
import {jobCounts} from './use-control-data.js';

export default function TasksPanel({service}){
 const c=jobCounts(service?.jobs);
 const facts=[['В работе',c.running,'is-live'],['В очереди',c.queued,''],['Ждут вход Google',c.waiting,'is-warn'],['Прервано',c.failed,'is-bad'],['Готово',c.done,'']];
 return <div className="cc-tasks">
  <dl className="cc-facts">{facts.map(([label,value,tone])=><div key={label}><dt>{label}</dt><dd className={'cc-num '+(value?tone:'')}>{value}</dd></div>)}</dl>
  {service?.status==='connected'?<ImportQueue service={service}/>:<p className="cc-hint">{service?.error||'Задачи появятся, когда сервер ответит.'}</p>}
 </div>;
}
