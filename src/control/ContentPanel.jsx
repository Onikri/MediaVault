import {useEffect,useMemo,useState} from 'react';
import {compileMangaPolicy,setMangaPolicy,normalizeTag} from '../manga-tag-policy.js';
import {addContentLabels,pastedLabels} from './content-policy-editor.js';
import './content-panel.css';

const TYPE={genre:'Жанр',tag:'Тег'};
const KIND={movie:'Фильмы',tv:'Сериалы',anime:'Аниме',manga:'Манга',ranobe:'Ранобэ',book:'Книги'};
function WordList({label,values,onChange,help}){
 const [text,setText]=useState('');
 return <section className="content-words"><h3>{label}</h3><p className="cc-hint">{help}</p>
  <div className="content-word-list">{values.map((value,index)=><span key={index}>{value}<button type="button" aria-label={'Удалить '+value} onClick={()=>onChange(values.filter((_,i)=>i!==index))}>×</button></span>)}{!values.length&&<p className="cc-hint">Список пуст</p>}</div>
  <form onSubmit={event=>{event.preventDefault();const added=pastedLabels(text);if(added.length){onChange([...new Set([...values,...added])]);setText('');}}}><label>{label}: новые значения<textarea rows={2} value={text} onChange={e=>setText(e.target.value)} placeholder="Одно значение на строку"/></label><button className="cc-button" disabled={!text.trim()}>Добавить</button></form>
 </section>;
}

export default function ContentPanel({service}){
 const [saved,setSaved]=useState(null),[draft,setDraft]=useState(null),[revision,setRevision]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [section,setSection]=useState('tags'),[query,setQuery]=useState(''),[selected,setSelected]=useState(''),[page,setPage]=useState(0),[bulk,setBulk]=useState(''),[category,setCategory]=useState('tag'),[job,setJob]=useState({state:'idle'}),[vocabulary,setVocabulary]=useState([]),[lookup,setLookup]=useState(''),[lookupBusy,setLookupBusy]=useState(false);
 const dirty=!!draft&&JSON.stringify(draft)!==JSON.stringify(saved);
 async function load(){setError('');try{const value=await service.request('/admin/content');setSaved(value.policy);setDraft(value.policy);setRevision(value.revision);setJob(value.job||{state:'idle'});}catch(e){setError(e.status===404?'Обновление управления контентом ещё не установлено на сервере.':e.message);}}
 useEffect(()=>{let alive=true;service.request('/admin/content').then(value=>{if(alive){setSaved(value.policy);setDraft(value.policy);setRevision(value.revision);setJob(value.job||{state:'idle'});}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[service.server]);
 useEffect(()=>{if(!dirty)return;const prevent=event=>{event.preventDefault();event.returnValue='';};addEventListener('beforeunload',prevent);return()=>removeEventListener('beforeunload',prevent);},[dirty]);
 useEffect(()=>{if(!['queued','running'].includes(job.state))return;const abort=new AbortController(),timer=setInterval(()=>service.request('/admin/content/job',{signal:abort.signal}).then(value=>{if(!abort.signal.aborted)setJob(value);}).catch(()=>{}),2000);return()=>{abort.abort();clearInterval(timer);};},[job.state,service.server]);
 useEffect(()=>{setLookupBusy(true);const abort=new AbortController(),timer=setTimeout(()=>service.request('/admin/content/vocabulary?'+new URLSearchParams({q:lookup}),{signal:abort.signal}).then(value=>{if(!abort.signal.aborted)setVocabulary(value.items||[]);}).catch(()=>{}).finally(()=>{if(!abort.signal.aborted)setLookupBusy(false);}),250);return()=>{clearTimeout(timer);abort.abort();};},[lookup,job.state,Math.floor((job.indexed||0)/100),revision,service.server]);
 const validation=useMemo(()=>{try{return {compiled:draft?compileMangaPolicy(draft):null};}catch(e){return {error:e.message};}},[draft]),compiled=validation.compiled;
 const filtered=useMemo(()=>{const term=normalizeTag(query);return (draft?.tags||[]).filter(row=>!term||[row.label,row.key,...row.aliases,...Object.values(row.sourceAliases||{}).flat()].some(value=>normalizeTag(value).includes(term)));},[draft,query]);
 const current=draft?.tags.find(row=>row.key===selected);
 function change(value){setDraft(value);setNotice('');setError('');}
 function edit(changes){change({...draft,tags:draft.tags.map(row=>row.key===selected?{...row,...changes}:row)});}
 function add(text=bulk,type=category){try{const result=addContentLabels(draft,text,type);change(result.policy);setBulk('');setNotice(result.added?'Добавлено: '+result.added+'. Сохрани, чтобы применить.':'Эти названия уже есть в справочнике.');}catch(e){setError(e.message);}}
 async function save(){setBusy(true);setError('');try{compileMangaPolicy(draft);const value=await service.request('/admin/content/policy',{method:'PUT',body:{revision,policy:draft}});setSaved(value.policy);setDraft(value.policy);setRevision(value.revision);if(value.job)setJob(value.job);
   // Only the public projection enters the shared client store.
   setNotice('Сохранено на Oracle. Обновлено тайтлов: '+(value.reindexedTitles||0)+'.');
   try{const publicValue=await service.request('/manga/tag-policy',{auth:false});setMangaPolicy(publicValue.policy,publicValue.revision,publicValue.scope);}catch{}
  }catch(e){setError(e.message);}finally{setBusy(false);}}
 async function refresh(){setBusy(true);setError('');try{setJob(await service.request('/admin/content/refresh',{method:'POST'}));}catch(e){setError(e.message);}finally{setBusy(false);}}
 return <div className="content-panel">
  <div className="content-intro"><p>Один справочник для фильмов, сериалов, аниме, манги, манхвы, маньхуа, книг и ранобэ.</p><span>Правила хранятся приватно на Oracle. Изменяет только владелец.</span>{draft&&<label className="content-auto"><input type="checkbox" checked={!!draft.includeDiscovered} onChange={event=>change({...draft,includeDiscovered:event.target.checked})}/>Все найденные теги, кроме исключений</label>}</div>
  <div className="content-tabs" role="tablist" aria-label="Управление контентом">{[['tags','Теги и жанры'],['exclusions','Исключения'],['sources','Источники и совпадения']].map(([key,label])=><button type="button" role="tab" aria-selected={section===key} key={key} onClick={()=>setSection(key)}>{label}</button>)}</div>
  {!draft&&!error&&<div className="content-skeleton" role="status">Загружаем приватный справочник…</div>}
  {error&&<p className="cc-error" role="alert">{error}<button type="button" className="cc-button" onClick={load}>Перечитать с сервера</button></p>}
  {validation.error&&<p className="cc-error" role="alert">{validation.error}</p>}
  {draft&&section==='tags'&&<>
   <form className="content-add" onSubmit={event=>{event.preventDefault();add();}}><label>Добавить названия из облака тегов<textarea rows={2} value={bulk} onChange={e=>setBulk(e.target.value)} placeholder="Вставь одно или несколько названий, по одному на строку"/></label><label>Категория<select value={category} onChange={e=>setCategory(e.target.value)}><option value="tag">Тег</option><option value="genre">Жанр</option></select></label><button className="cc-button" disabled={!bulk.trim()}>Добавить в справочник</button></form>
   <label>Найти тег, жанр или синоним<input type="search" value={query} onChange={e=>{setQuery(e.target.value);setPage(0);}}/></label>
   <div className="content-workspace"><div className="content-rule-list" aria-label="Теги и жанры"><p className="cc-hint">Найдено: {filtered.length} · всего: {draft.tags.length}</p>{filtered.slice(page*35,(page+1)*35).map(row=><button type="button" key={row.key} className={selected===row.key?'is-selected':''} onClick={()=>setSelected(row.key)}><strong>{row.label}</strong><span>{TYPE[row.category]||'По источнику'} · {compiled?.key(row.label)?'Виден':'Скрыт исключением'}</span></button>)}{!filtered.length&&<p>Совпадений нет. Добавь новое название выше.</p>}
    {filtered.length>35&&<div className="content-pages"><button type="button" className="cc-button" disabled={!page} onClick={()=>setPage(page-1)}>Назад</button><span>{page+1} / {Math.ceil(filtered.length/35)}</span><button type="button" className="cc-button" disabled={(page+1)*35>=filtered.length} onClick={()=>setPage(page+1)}>Далее</button></div>}
   </div>
   {current?<section className="content-rule-editor" aria-label="Редактор тега"><h2>{current.label}</h2><label>Отображаемое название<input value={current.label} maxLength={120} onChange={e=>edit({label:e.target.value})}/></label><label>Категория<select value={current.category||''} onChange={e=>edit({category:e.target.value||undefined})}><option value="">Как у источника</option><option value="tag">Тег</option><option value="genre">Жанр</option></select></label>
    <WordList key={current.key} label="Синонимы на всех источниках" values={current.aliases} onChange={aliases=>edit({aliases})} help="Названия на русском, английском, японском и других языках. Похожие по смыслу названия объединяешь ты."/>
    <SourceAliases key={current.key} value={current.sourceAliases||{}} onChange={sourceAliases=>edit({sourceAliases})}/>
    <button type="button" className="cc-button is-quiet-danger content-remove" onClick={()=>{change({...draft,hiddenTags:[...new Set([...(draft.hiddenTags||[]),current.key])]});setSelected('');}}>Удалить тег из каталога</button>
   </section>:<section className="content-rule-editor content-empty"><h2>Выбери название</h2><p>Здесь меняются подпись, категория и соответствия на разных сайтах. Любую запись можно удалить.</p></section>}
   </div>
  </>}
  {draft&&section==='exclusions'&&<div className="content-exclusions"><WordList label="Запрещённые слова и фразы" values={draft.excludedTerms} onChange={excludedTerms=>change({...draft,excludedTerms})} help="Совпадение по целому слову или фразе скрывает тег со всеми его синонимами во всех разделах."/><WordList label="Запрещённые начала слов" values={draft.excludedPrefixes} onChange={excludedPrefixes=>change({...draft,excludedPrefixes})} help="Скрывает теги, где слово начинается с указанного значения. Каждую запись можно изменить или удалить."/><WordList label="Скрытые теги целиком" values={draft.hiddenTags||[]} onChange={hiddenTags=>change({...draft,hiddenTags})} help="Точное скрытие названий без удаления карточек. Удали запись, чтобы вернуть тег."/></div>}
  {draft&&section==='sources'&&<>
   <div className="content-job"><div><h2>Обновление источников</h2><p className="cc-hint">Сохранённые факты переиндексируются сразу. Новые метаданные загружаются ограниченными пачками; закрытые сайты и недоступные каталоги показаны отдельно.</p></div><button type="button" className="cc-button" disabled={busy||['queued','running'].includes(job.state)} onClick={refresh}>Проверить источники</button>
    {job.total>0&&<><progress max={job.total} value={job.completed||0} aria-label="Проверка источников"/><span>{job.completed||0} / {job.total} · записей добавлено: {job.indexed||0}</span></>}
    {job.error&&<p className="cc-error">{job.error}</p>}{job.sources?.map(row=><div className="content-source-state" key={row.key||row.domain+row.name}><strong>{row.name}</strong><span>{job.continuous?(row.error||({'queued':'В очереди','running':'Собираем каталог','done':'Обход завершён','partial':'Каталог собран частично','unsupported':'Нет доступного каталога','retry':'Повторяем позже'}[row.status]||row.status))+' · страниц: '+(row.pages||0)+' · записей: '+row.indexed:row.status==='partial'?'Совпадений: '+row.matched+' · тайтлов: '+row.indexed:row.status==='closed'?'Сайт закрыт':'Каталог тегов недоступен'}{row.limited?' · первая пачка':''}</span></div>)}
    {job.remainingKeys>0&&<p className="cc-hint">В очереди ещё тегов: {job.remainingKeys}. Следующая пачка запустится автоматически.</p>}
   </div>
   <label>Проверить исходное название или найти похожие<input type="search" value={lookup} onChange={e=>setLookup(e.target.value)} placeholder="Название из облака тегов"/></label>
   <div className="content-matches" aria-busy={lookupBusy}>{vocabulary.map(row=><div key={row.label}><div><strong>{row.label}</strong><p>{row.works} тайтлов · {row.sources.join(', ')||'Каталоги метаданных'}</p><small>{row.keys?.length?'Уже сопоставлен со справочником':'Нет соответствия'} · {row.kinds.map(kind=>KIND[kind]||kind).join(', ')}</small></div><button type="button" className="cc-button" onClick={()=>add(row.label,row.category==='genres'?'genre':'tag')}>{draft.includeDiscovered?'Настроить':'Добавить'}</button>{draft.includeDiscovered&&<button type="button" className="cc-button" onClick={()=>change({...draft,hiddenTags:[...new Set([...(draft.hiddenTags||[]),row.label])]})}>Скрыть тег</button>}{current&&<button type="button" className="cc-button" onClick={()=>{edit({aliases:[...new Set([...current.aliases,row.label])]});setNotice('Добавлен синоним к «'+current.label+'». Сохрани изменения.');}}>Синоним к «{current.label}»</button>}</div>)}{!lookupBusy&&!vocabulary.length&&<p>В собранных метаданных совпадений пока нет. Можно добавить название вручную и проверить доступные источники.</p>}</div>
  </>}
  {notice&&<p className="content-notice" role="status">{notice}</p>}
  {dirty&&<div className="cc-savebar"><span>Есть несохранённые изменения</span><button type="button" className="cc-button" disabled={busy} onClick={()=>{setDraft(saved);setError('');setNotice('');}}>Отменить изменения</button><button type="button" className="btn btn-primary" disabled={busy||!compiled} onClick={save}>{busy?'Применяем…':'Сохранить и переиндексировать'}</button></div>}
 </div>;
}

function SourceAliases({value,onChange}){
 const [domain,setDomain]=useState(''),[text,setText]=useState(''),[error,setError]=useState('');
 return <section className="content-words"><h3>Синонимы отдельного источника</h3>{Object.entries(value).map(([host,aliases])=><WordList key={host} label={host} values={aliases} onChange={next=>{const result={...value};if(next.length)result[host]=next;else delete result[host];onChange(result);}} help="Действуют только на этом домене"/>)}
  <form onSubmit={event=>{event.preventDefault();const host=domain.trim().toLowerCase();if(!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(host)||!host.includes('.')){setError('Укажи домен без https:// и пути.');return;}const names=pastedLabels(text);if(!names.length)return;onChange({...value,[host]:[...new Set([...(value[host]||[]),...names])]});setDomain('');setText('');setError('');}}><label>Домен источника<input value={domain} onChange={e=>setDomain(e.target.value)} placeholder="example.org"/></label><label>Название на источнике<textarea rows={2} value={text} onChange={e=>setText(e.target.value)}/></label>{error&&<p role="alert">{error}</p>}<button className="cc-button">Добавить соответствие</button></form>
 </section>;
}
