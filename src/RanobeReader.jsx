import {useEffect,useRef,useState} from 'react';
import ReaderShell from './ReaderShell.jsx';
import {bookPreferences,saveBookPreferences} from './book-content.js';
import {readRanobeChapter,saveRanobeProgress} from './ranobe-client.js';
import Narration from './tts/Narration.jsx';
import RoleText,{segmentsByParagraph} from './tts/RoleText.jsx';
import {Headphones,Pause} from 'lucide-react';
import './reader-surface.css';
import './ranobe.css';

// Online light-novel reader: one chapter as a continuous column of paragraphs,
// chapter-to-chapter navigation and narration that follows the text.
export default function RanobeReader({book,item,start,service,userId,onClose}){
 const root=useRef(null),body=useRef(null),restored=useRef(false),follow=useRef(true),scrollPause=useRef(0);
 const [prefs,setPrefs]=useState(()=>bookPreferences(userId)),[settings,setSettings]=useState(false);
 const [index,setIndex]=useState(start?.index||0),[chapter,setChapter]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 const [speaking,setSpeaking]=useState(-1),[speakingSegment,setSpeakingSegment]=useState(null),[script,setScript]=useState(null),voice=useRef(null),[voicePlaying,setVoicePlaying]=useState(false),[continueVoice,setContinueVoice]=useState(false),[startParagraph,setStartParagraph]=useState(start?.paragraph||0);
 const entry=book.episodes[index];
 function update(change){setPrefs(old=>{const next={...old,...change};saveBookPreferences(userId,next);return next;});}

 useEffect(()=>{
  if(!entry)return;const abort=new AbortController();
  setLoading(true);setError('');setChapter(null);setSpeaking(-1);setSpeakingSegment(null);setScript(null);
  readRanobeChapter(service,entry.url,item,{signal:abort.signal}).then(data=>{
   setChapter(data);setLoading(false);
   const next=book.episodes[index+1];if(next)readRanobeChapter(service,next.url,item).catch(()=>{});
  }).catch(e=>{if(!abort.signal.aborted){setError(e.message||'Не удалось открыть главу.');setLoading(false);}});
  return()=>abort.abort();
 },[entry?.url]);

 // Restore the saved paragraph once, then keep the reading position.
 useEffect(()=>{
  if(!chapter||!body.current)return;
  const target=restored.current?0:startParagraph;restored.current=true;
  requestAnimationFrame(()=>{const node=body.current?.querySelector('[data-p="'+target+'"]');if(node&&target>0)node.scrollIntoView({block:'start'});else body.current?.scrollTo({top:0});});
  const observer=new IntersectionObserver(rows=>{
   const visible=rows.filter(r=>r.isIntersecting).map(r=>Number(r.target.dataset.p)).sort((a,b)=>a-b)[0];
   if(Number.isFinite(visible))saveRanobeProgress(userId,book.url,{chapter:entry.url,paragraph:visible,title:entry.title});
  },{root:body.current,rootMargin:'-30% 0px -60% 0px'});
  body.current.querySelectorAll('[data-p]').forEach(n=>observer.observe(n));
  return()=>observer.disconnect();
 },[chapter]);

 function go(next,{keepVoice=false}={}){
  if(next<0||next>=book.episodes.length)return;
  setContinueVoice(keepVoice);setStartParagraph(0);setIndex(next);
  saveRanobeProgress(userId,book.url,{chapter:book.episodes[next].url,paragraph:0,title:book.episodes[next].title});
 }
 function speakingRow(row){
  setSpeaking(row.p);setSpeakingSegment(row.segment);
  if(!follow.current||Date.now()<scrollPause.current)return;
  const node=body.current?.querySelector('[data-p="'+row.p+'"]');
  node?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
 }

 const surface={'--book-width':prefs.width+'px','--book-font':prefs.font==='serif'?'Georgia,serif':'system-ui,sans-serif','--book-size':prefs.size+'px','--book-leading':prefs.lineHeight};
 const options=<div className="reader-book-settings">
  <label>Тема<select aria-label="Тема ранобэ" value={prefs.theme} onChange={e=>update({theme:e.target.value})}><option value="paper">Бумага</option><option value="dark">Тёмная</option><option value="black">Чёрная · OLED</option></select></label>
  <label>Шрифт<select aria-label="Шрифт ранобэ" value={prefs.font} onChange={e=>update({font:e.target.value})}><option value="serif">Книжный</option><option value="sans">Без засечек</option></select></label>
  <label>Размер текста<select aria-label="Размер текста ранобэ" value={prefs.size} onChange={e=>update({size:Number(e.target.value)})}>{[16,18,20,22,24,28].map(v=><option key={v} value={v}>{v} px</option>)}</select></label>
  <label>Интерлиньяж<select aria-label="Межстрочный интервал ранобэ" value={prefs.lineHeight} onChange={e=>update({lineHeight:Number(e.target.value)})}>{[1.5,1.75,2].map(v=><option key={v} value={v}>{v}</option>)}</select></label>
  <label>Ширина<select aria-label="Ширина текста ранобэ" value={prefs.width} onChange={e=>update({width:Number(e.target.value)})}>{[560,720,900,1100].map(v=><option key={v} value={v}>{v} px</option>)}</select></label>
  <label className="narration-switch"><input type="checkbox" defaultChecked onChange={e=>{follow.current=e.target.checked;}}/>Следовать за голосом</label>
  <label className="narration-switch"><input type="checkbox" checked={prefs.roles} onChange={e=>update({roles:e.target.checked})}/>Показывать роли в тексте</label>
 </div>;
 const contents=<nav className="reader-chapter-list">{book.episodes.map((c,i)=><button key={c.url} aria-current={i===index||undefined} onClick={()=>go(i)}><span translate="no">{c.number}. {c.title}</span></button>)}</nav>;
 const narration=chapter&&<Narration key={entry.url} paragraphs={chapter.paragraphs} language={chapter.language||book.language} bookKey={book.url} chapterKey={entry.url}
  title={book.title+' · '+(chapter.title||entry.title)} service={service} userId={userId} startParagraph={startParagraph} autoplay={continueVoice}
  onAutoplayHandled={()=>setContinueVoice(false)} onSpeaking={speakingRow} onFinished={()=>go(index+1,{keepVoice:true})}
  onScript={setScript} commandRef={voice} onPlaying={setVoicePlaying}/>;
 const byParagraph=script?segmentsByParagraph(script.segments):null;
 const listen=<button className="reader-control reader-listen" aria-label={voicePlaying?'Пауза озвучки':'Слушать главу'} aria-pressed={voicePlaying} disabled={!chapter} onClick={()=>voice.current?.toggle()}>{voicePlaying?<Pause size={19}/>:<Headphones size={19}/>}</button>;
 return <ReaderShell readerRef={root} title={book.title} subtitle={'Глава '+entry?.number+(entry?.title?' · '+entry.title:'')} onClose={onClose} theme={prefs.theme}
  className="book-reader ranobe-reader" paged={false} actions={listen} settings={options} settingsOpen={settings} onSettingsOpenChange={setSettings} contents={contents}
  progress={{current:index+1,total:book.episodes.length,label:'Глава '+(index+1)+' / '+book.episodes.length}}
  onPrevious={()=>go(index-1)} onNext={()=>go(index+1)} canPrevious={index>0} canNext={index<book.episodes.length-1}>
  <div ref={body} className="book-reading-surface book-flow-scroll ranobe-surface" style={surface} onWheel={()=>{scrollPause.current=Date.now()+4000;}} onTouchMove={()=>{scrollPause.current=Date.now()+4000;}}>
   {loading&&<div className="reader-book-loading" role="status">Открываем главу…</div>}
   {error&&<div className="reader-book-error" role="alert">{error} <button type="button" className="text-link" onClick={()=>{setIndex(i=>i);setChapter(null);readRanobeChapter(service,entry.url,item).then(setChapter).catch(e=>setError(e.message));}}>Повторить</button></div>}
   {chapter&&<article className="reader-prose ranobe-prose" translate="no" lang={chapter.language||book.language}>
    <h2>{chapter.title||entry.title}</h2>
    {chapter.paragraphs.map((text,i)=><p key={i} data-p={i} className={i===speaking?'is-speaking':undefined}><RoleText text={text} segments={byParagraph?.get(i)} colors={script?.colors} speaking={i===speaking?speakingSegment:null} show={prefs.roles}/></p>)}
    <footer className="ranobe-chapter-end">{index<book.episodes.length-1?<button type="button" className="btn btn-primary" onClick={()=>go(index+1)}>Следующая глава</button>:<p>Это последняя опубликованная глава.</p>}</footer>
   </article>}
   {narration&&<div className="ranobe-narration-dock" onClick={e=>e.stopPropagation()}>{narration}</div>}
  </div>
 </ReaderShell>;
}
