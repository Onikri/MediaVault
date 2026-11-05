import UiSelect from './UiSelect.jsx';
import {useMemo,useState} from 'react';
import {ArrowRight,Cloud,LayoutGrid,List,Table2} from 'lucide-react';
import './import-queue.css';
const names={queued:'В очереди',running:'Выполняется',completed:'Завершено',failed:'Прервано',waiting_auth:'Нужен вход Google',cancelling:'Останавливается',cancelled:'Остановлено',merged:'Объединено'};
const phases={queued:'Ожидает выполнения',artwork:'Получаем изображения',preparing:'Подготовка',downloading:'Скачиваем файл',assembling:'Собираем видео',uploading:'Шифруем и записываем в Drive',episode_done:'Файл добавлен',done:'Готово',failed:'Нужно продолжить',merged:'Объединено с другим заданием'};
const active=new Set(['running','queued','cancelling']);
function initial(){try{return JSON.parse(localStorage.getItem('mv_import_queue_view_v1'))||{};}catch{return {};}}
export default function ImportQueue({service}){
 const [error,setError]=useState(''),[options,setOptions]=useState(initial),[filter,setFilter]=useState('all');
 const view=options.view||'list',sort=options.sort||'active',group=options.group||'none';
 function change(patch){setOptions(old=>{const next={...old,...patch};try{localStorage.setItem('mv_import_queue_view_v1',JSON.stringify(next));}catch{}return next;});}
 async function action(id,name){try{setError('');await service[name](id);}catch(cause){setError(cause.message);}}
 const groups=useMemo(()=>{
  const rows=service.jobs.filter(j=>filter==='all'?j.status!=='merged':filter==='active'?active.has(j.status):j.status===filter).slice();
  rows.sort((a,b)=>(sort==='active'?Number(active.has(b.status))-Number(active.has(a.status)):0)||(sort==='old'?a.created-b.created:sort==='updated'?b.updated-a.updated:b.created-a.created));
  const output=new Map();for(const job of rows){const p=job.progress||{},key=group==='status'?names[job.status]:group==='title'?p.title||'Без названия':group==='type'?p.taskType==='enrich'?'Оформление':'Импорт':'';if(!output.has(key))output.set(key,[]);output.get(key).push(job);}return [...output];
 },[service.jobs,filter,sort,group]);
 const waiting=service.jobs.filter(j=>j.status==='waiting_auth').length;
 return <section className={'import-queue queue-view-'+view} aria-label="Очередь заданий"><div className="section-heading"><h2 className="section-title">Задания</h2><span className="source-label">На ВМ · активных: {service.jobs.filter(j=>active.has(j.status)).length}</span></div>
 {waiting>0&&<aside className="queue-auth-wait"><strong>{waiting} заданий ждут разрешение Google</strong><p>Готовые файлы сохранены. Ожидание входа не занимает очередь выполнения.</p><button onClick={()=>service.connect().catch(e=>setError(e.message))}>Обновить фоновый доступ Drive</button></aside>}
 <div className="queue-toolbar"><div className="catalog-views" role="group" aria-label="Вид заданий">{[['list','Список',List],['cards','Карточки',LayoutGrid],['table','Таблица',Table2]].map(([id,label,Glyph])=><button key={id} aria-label={label} title={label} aria-pressed={view===id} onClick={()=>change({view:id})}><Glyph size={17}/></button>)}</div>
 <label>Состояние<UiSelect aria-label="Состояние заданий" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">Все</option><option value="active">Активные</option>{Object.entries(names).map(([id,label])=><option key={id} value={id}>{label}</option>)}</UiSelect></label>
 <label>Сначала<UiSelect aria-label="Сортировка заданий" value={sort} onChange={e=>change({sort:e.target.value})}><option value="active">Активные</option><option value="new">Новые</option><option value="old">Старые</option><option value="updated">Обновлённые</option></UiSelect></label>
 <label>Группировать<UiSelect aria-label="Группировка заданий" value={group} onChange={e=>change({group:e.target.value})}><option value="none">Без группировки</option><option value="title">По тайтлу</option><option value="type">По операции</option><option value="status">По состоянию</option></UiSelect></label></div>
 {error&&<p role="alert" className="inline-error">{error}</p>}
 {!groups.length&&<div className="catalog-empty"><Cloud size={28}/><p>{service.jobs.length?'Нет заданий с этим фильтром':'Здесь появятся задания импорта и оформления'}</p></div>}
 {groups.map(([name,jobs])=><section className="queue-group" key={name}>{name&&<h3>{name}<small>{jobs.length}</small></h3>}<div className="queue-items">{jobs.map(job=>{const p=job.progress||{},finished=(p.saved||0)+(p.skipped||0)+(p.failed||0),count=p.taskType==='enrich'?Math.max(p.cursor||0,finished):finished,percent=p.total?Math.min(100,Math.round(count/p.total*100)):0;
 return <article key={job.id} className={'queue-task status-'+job.status} id={'job-'+job.id}><div className="queue-task-top"><span className={'queue-status status-'+job.status}><i/>{names[job.status]||job.status}</span><time dateTime={new Date(job.created*1000).toISOString()}>{new Date(job.created*1000).toLocaleDateString('ru-RU')}</time></div>
 <div className="queue-task-name"><small>{p.taskType==='enrich'?'Оформление':'Импорт'}</small><h3>{p.title||'Библиотека'}</h3>{p.file&&<p title={p.file}>{p.file}</p>}</div>
 <div className="queue-task-activity"><p>{active.has(job.status)?p.operation||phases[p.phase]||'Ожидаем ответ':phases[p.phase]||names[job.status]}</p>{job.status==='queued'&&job.queuePosition&&<small>Позиция {job.queuePosition}</small>}{job.status==='running'&&<small>Обновлено {new Date(job.updated*1000).toLocaleTimeString('ru-RU')}</small>}</div>
 <div className="queue-task-progress"><div className="progress-track" role="progressbar" aria-label={'Прогресс '+(p.title||'задания')} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><div className="progress-fill" style={{width:percent+'%'}}/></div><div className="queue-task-meta"><span>{count}{p.total?' / '+p.total:''} файлов</span>{job.status==='running'&&p.current>0&&<span>Сейчас №{p.current}</span>}{p.bytesTotal>0&&job.status==='running'&&<span>{Math.min(100,Math.round((p.bytesLoaded||0)/p.bytesTotal*100))}% файла</span>}</div></div>
 <div className="queue-task-detail">{job.status==='running'&&p.mbps!=null&&<small>Drive: {p.mbps} МБ/с · AES-GCM: {Math.round(p.encryptionMs||0)} мс</small>}{job.status==='running'&&Date.now()/1000-job.updated>90&&<small>Давно нет прогресса. Ожидаем источник или Drive.</small>}{p.message&&<small>{p.message}</small>}{p.mergedInto&&<a href={'#job-'+p.mergedInto} onClick={e=>{e.preventDefault();setFilter('all');requestAnimationFrame(()=>document.getElementById('job-'+p.mergedInto)?.scrollIntoView({block:'center',behavior:'smooth'}));}}>Основное задание</a>}</div>
 <div className="queue-task-actions">{['queued','running'].includes(job.status)&&<button onClick={()=>action(job.id,'cancel')}>Остановить</button>}{['failed','waiting_auth'].includes(job.status)&&<button onClick={()=>action(job.id,'resume')}>Продолжить<ArrowRight size={13}/></button>}</div></article>;
 })}</div></section>)}
 </section>;
}
