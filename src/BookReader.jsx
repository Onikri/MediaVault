import {useEffect,useMemo,useRef,useState} from 'react';
import Narration from './tts/Narration.jsx';
import RoleText,{segmentsByParagraph} from './tts/RoleText.jsx';
import {Headphones,Pause} from 'lucide-react';
import ReaderShell from './ReaderShell.jsx';
import {splitBookText,decodeBookText,fictionBook,bookProgress,saveBookProgress,bookPreferences,saveBookPreferences,bookPageCapacity,paginateBookRows,pageAtOffset} from './book-content.js';
import './reader-surface.css';
import './ranobe.css';

// Readable paragraphs of one PDF page from its text layer: lines are joined,
// hyphenated breaks are rejoined, a larger vertical gap or a dialogue dash
// starts a new paragraph. Scanned pages without a text layer give nothing.
export async function pdfParagraphs(doc,index){
 const page=await doc.getPage(index+1),content=await page.getTextContent();
 const lines=[];let text='',y=null;
 for(const item of content.items){
  if(typeof item.str!=='string')continue;
  const at=item.transform?.[5]??0;
  if(y!==null&&Math.abs(at-y)>2&&text.trim()){lines.push({text:text.trim(),y});text='';}
  text+=item.str;y=at;
  if(item.hasEOL&&text.trim()){lines.push({text:text.trim(),y});text='';y=null;}
 }
 if(text.trim())lines.push({text:text.trim(),y});
 const gaps=lines.slice(1).map((l,i)=>Math.abs(lines[i].y-l.y)).filter(g=>g>0&&g<200).sort((a,b)=>a-b),usual=gaps[Math.floor(gaps.length/2)]||14;
 const out=[];let current='';
 lines.forEach((line,i)=>{
  const gap=i?Math.abs(lines[i-1].y-line.y):0,fresh=i&&(gap>usual*1.55||/^[—–]\s/.test(line.text));
  if(fresh&&current){out.push(current);current='';}
  current=current?(/[-‐]$/.test(current)&&/^[a-zа-яёіїєґ]/.test(line.text)?current.replace(/[-‐]$/,'')+line.text:current+' '+line.text):line.text;
 });
 if(current)out.push(current);
 return out.map(t=>t.replace(/\s+/g,' ').trim()).filter(t=>t.length>1&&!/^\d{1,4}$/.test(t));
}

function PdfPage({document:pdf,index,active,onVisible,available,maxWidth}){
 const host=useRef(null),canvas=useRef(null),[near,setNear]=useState(active),[ratio,setRatio]=useState(.707),[error,setError]=useState('');
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{const visible=entries.some(v=>v.isIntersecting);setNear(visible);if(visible)onVisible?.(index);},{rootMargin:'80% 0px'});observer.observe(host.current);return()=>observer.disconnect();},[index]);
 useEffect(()=>{if(!near&&!active)return;let closed=false,task;setError('');pdf.getPage(index+1).then(page=>{if(closed)return;const natural=page.getViewport({scale:1});setRatio(natural.width/natural.height);const width=Math.min(maxWidth,available.width,active?available.height*natural.width/natural.height:1600);host.current.style.width=width+'px';const viewport=page.getViewport({scale:width/natural.width*Math.min(devicePixelRatio||1,2)});const node=canvas.current;node.width=viewport.width;node.height=viewport.height;task=page.render({canvasContext:node.getContext('2d'),viewport});return task.promise;}).catch(e=>{if(!closed&&e.name!=='RenderingCancelledException')setError('Не удалось отобразить страницу PDF.');});return()=>{closed=true;task?.cancel();};},[pdf,index,near,active,available,maxWidth]);
 return <figure ref={host} data-book-page={index} className="reader-pdf-page" style={{aspectRatio:ratio}}><canvas ref={canvas} role="img" aria-label={'Страница PDF '+(index+1)}/>{error&&<p role="alert">{error}</p>}</figure>;
}

export default function BookReader({item,userId,libraryId,onClose,readWhole,inline=false,readerService,service=readerService}){
 const loadedItem=useRef(null),textRows=useRef([]),root=useRef(null),epubHost=useRef(null),epub=useRef(null),view=useRef(null),pdf=useRef(null),live=useRef({readWhole}),saved=useRef(null);live.current={readWhole};
 const [viewport,setViewport]=useState(()=>({width:innerWidth,height:innerHeight}));
 const [prefs,setPrefs]=useState(()=>bookPreferences(userId)),[settings,setSettings]=useState(false),[pages,setPages]=useState([]),[page,setPage]=useState(0),[total,setTotal]=useState(0),[toc,setToc]=useState([]),[busy,setBusy]=useState(true),[error,setError]=useState(''),[kind,setKind]=useState(''),[epubReady,setEpubReady]=useState(0),[epubLabel,setEpubLabel]=useState('Книга');
 const prefsRef=useRef(prefs),swipeUntil=useRef(0);prefsRef.current=prefs;
 const extension=String(item.name||'').split('.').pop().toLowerCase();
 useEffect(()=>{let timer;const resize=()=>{clearTimeout(timer);timer=setTimeout(()=>setViewport({width:innerWidth,height:innerHeight}),150);};addEventListener('resize',resize);return()=>{clearTimeout(timer);removeEventListener('resize',resize);};},[]);
 function update(change){setPrefs(old=>{const next={...old,...change};saveBookPreferences(userId,next);return next;});}
 useEffect(()=>{const abort=new AbortController();let book,document,closed=false;loadedItem.current=null;setBusy(true);setError('');setPages([]);setTotal(0);setToc([]);textRows.current=[];setKind(extension);saved.current=bookProgress(userId,libraryId,item.id);setPage(saved.current?.page||0);
  (async()=>{
   const blob=await live.current.readWhole(item,{signal:abort.signal});if(closed)return;
   if(extension==='pdf'){
    const lib=await import('pdfjs-dist');lib.GlobalWorkerOptions.workerSrc=(await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
    const task=lib.getDocument({data:new Uint8Array(await blob.arrayBuffer()),isEvalSupported:false,useSystemFonts:true});abort.signal.addEventListener('abort',()=>task.destroy(),{once:true});document=await task.promise;if(closed){document.destroy();return;}pdf.current=document;setTotal(document.numPages);setPage(Math.min(saved.current?.page||0,document.numPages-1));
   }else if(extension==='epub'){
    const ePub=(await import('epubjs')).default;abort.signal.throwIfAborted();
    book=ePub(await blob.arrayBuffer());epub.current=book;const rendition=book.renderTo(epubHost.current,{width:'100%',height:'100%',flow:prefs.mode==='scroll'?'scrolled-doc':'paginated',spread:'auto',allowScriptedContent:false});view.current=rendition;
    rendition.hooks.content.register(contents=>{let start=null;contents.document.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'&&!e.buttons&&(e.clientY<65||contents.window.innerHeight-e.clientY<65))root.current?.dispatchEvent(new Event('reader-show-chrome'));});contents.document.addEventListener('pointerdown',e=>{if(e.pointerType==='touch'&&e.isPrimary)start={x:e.clientX,y:e.clientY};});contents.document.addEventListener('pointerup',e=>{if(!start)return;const dx=e.clientX-start.x,dy=e.clientY-start.y;start=null;if(prefsRef.current.mode==='pages'&&Math.abs(dx)>70&&Math.abs(dy)<40){swipeUntil.current=Date.now()+400;(dx<0?rendition.next():rendition.prev()).catch(()=>{});}});});
    rendition.on('click',event=>{if(Date.now()<swipeUntil.current||event.view?.getSelection()?.toString())return;const width=event.view?.innerWidth||innerWidth;const x=event.clientX/width;if(prefsRef.current.mode!=='scroll'&&(x<.26||x>.74)){(x>.74?rendition.next():rendition.prev()).catch(()=>{});}else root.current?.dispatchEvent(new Event('reader-toggle-chrome'));});
    rendition.on('keydown',event=>{if(['ArrowLeft','ArrowRight',' '].includes(event.key)){event.preventDefault();(event.key==='ArrowLeft'?rendition.prev():rendition.next()).catch(()=>{});}if(event.key==='Escape')root.current?.dispatchEvent(new Event('reader-toggle-chrome'));});
    rendition.on('relocated',location=>{if(!closed)readEpubSection(rendition,location);});
    rendition.on('relocated',location=>{if(closed)return;const n=location.start?.displayed?.page||1,m=location.start?.displayed?.total||1;setEpubLabel(n+' / '+m+' · в главе');saveBookProgress(userId,libraryId,item.id,{cfi:location.start?.cfi,page:0});});
    await rendition.display(saved.current?.cfi||undefined);if(closed)return;setEpubReady(v=>v+1);
    const navigation=await book.loaded.navigation;if(!closed)setToc(navigation.toc||[]);
   }else if(['txt','fb2'].includes(extension)){
    if(blob.size>20*1024**2)throw Error('Для текстовой книги больше 20 МБ используй EPUB или PDF.');
    const text=decodeBookText(await blob.arrayBuffer()),rows=extension==='fb2'?fictionBook(text):splitBookText(text).map((content,i)=>({content,title:'Часть '+(i+1)}));if(!rows.length)throw Error('В книге не найден текст.');if(closed)return;textRows.current=rows;const fitted=paginateBookRows(rows,bookPageCapacity(Math.min(prefsRef.current.width,innerWidth),innerHeight,prefsRef.current.size,prefsRef.current.lineHeight));setPages(fitted);setTotal(fitted.length);setPage(saved.current?.offset!=null?pageAtOffset(fitted,saved.current.offset):Math.min(saved.current?.page||0,fitted.length-1));setToc(fitted.map((row,i)=>({label:row.title,index:i})));
   }else throw Error('Поддерживаются EPUB, PDF, FB2 и TXT.');
   if(!closed){loadedItem.current=item.id;setBusy(false);}
  })().catch(e=>{if(!closed&&e.name!=='AbortError'){setError(e.message);setBusy(false);}});
  return()=>{closed=true;abort.abort();view.current=null;epub.current=null;pdf.current=null;try{for(const url of Object.values(book?.archive?.urlCache||{}))if(typeof url==='string'&&url.startsWith('blob:'))URL.revokeObjectURL(url);book?.destroy();document?.destroy();}catch{}};
 },[item.id,userId,libraryId]);
 useEffect(()=>{if(!total||loadedItem.current!==item.id)return;saveBookProgress(userId,libraryId,item.id,{page,pages:total,...(pages.length?{offset:pages.slice(0,page).reduce((sum,row)=>sum+row.content.length,0)}:{})});},[page,total,item.id,userId,libraryId]);
 useEffect(()=>{if(!textRows.current.length)return;const offset=pages.slice(0,page).reduce((sum,row)=>sum+row.content.length,0),fitted=paginateBookRows(textRows.current,bookPageCapacity(Math.min(prefs.width,viewport.width),viewport.height,prefs.size,prefs.lineHeight));setPages(fitted);setTotal(fitted.length);setPage(pageAtOffset(fitted,offset));setToc(fitted.map((row,i)=>({label:row.title,index:i})));},[prefs.size,prefs.width,prefs.lineHeight,viewport]);
 useEffect(()=>{const rendition=view.current;if(!rendition)return;const paper={paper:'#eee7da',dark:'#161718',black:'#000'}[prefs.theme],ink=prefs.theme==='paper'?'#25231f':'#e5e0d7';rendition.themes.default({'body':{'background':paper+'!important','color':ink+'!important','font-family':(prefs.font==='serif'?'Georgia,serif':'system-ui,sans-serif')+'!important','line-height':prefs.lineHeight+'!important','padding':'28px 22px!important'},'p':{'line-height':prefs.lineHeight+'!important'},'img':{'max-width':'100%!important','height':'auto!important'}});rendition.themes.fontSize(prefs.size+'px');rendition.flow(prefs.mode==='scroll'?'scrolled-doc':'paginated');},[prefs,epubReady]);
 const [speaking,setSpeaking]=useState(null),[voiceSection,setVoiceSection]=useState(null),[continueVoice,setContinueVoice]=useState(false);
 const [pdfSection,setPdfSection]=useState(null),[epubSection,setEpubSection]=useState(null),[script,setScript]=useState(null),[voicePlaying,setVoicePlaying]=useState(false);
 const voice=useRef(null),epubNodes=useRef([]),epubContents=useRef(null),epubLast=useRef(null);
 function readEpubSection(rendition,location){
  const index=location?.start?.index,href=location?.start?.href;if(index==null)return;
  const contents=(rendition.getContents?.()||[]).find(c=>c.sectionIndex===index)||(rendition.getContents?.()||[])[0];const doc=contents?.document;if(!doc?.body)return;
  if(epubContents.current?.document===doc)return;
  epubContents.current=contents;
  if(!doc.getElementById('mv-tts-style'))doc.head?.insertAdjacentHTML('beforeend','<style id="mv-tts-style">.mv-speaking{background:rgba(238,60,53,.16);border-radius:6px}</style>');
  const nodes=[...doc.body.querySelectorAll('p,h1,h2,h3,h4,h5,h6,li,blockquote,div')].filter(n=>!n.querySelector('p,div,li,blockquote,h1,h2,h3,h4,h5,h6')&&n.textContent.trim().length>1);
  epubNodes.current=nodes;
  const label=(toc.find(t=>t.href&&href&&t.href.split('#')[0]===href.split('#')[0])?.label||'').trim();
  setEpubSection({title:label||'Глава '+(index+1),sectionIndex:index,first:0,last:0,rows:nodes.map((n,i)=>({text:n.textContent.replace(/\s+/g,' ').trim(),page:0,n:i})),key:item.id+':epub:'+index});
 }
 useEffect(()=>{
  if(kind!=='pdf'||busy||!pdf.current)return;let closed=false;
  pdfParagraphs(pdf.current,page).then(rows=>{if(!closed)setPdfSection({title:'Страница '+(page+1),first:page,last:page,rows:rows.map((text,n)=>({text,page,n})),key:item.id+':pdf:'+page});}).catch(()=>{if(!closed)setPdfSection(null);});
  return()=>{closed=true;};
 },[kind,page,busy,item.id]);
 const section=useMemo(()=>{
  if(!pages.length||!['txt','fb2'].includes(kind))return null;
  const title=pages[Math.min(page,pages.length-1)]?.title;let first=page,last=page;
  while(first>0&&pages[first-1].title===title)first--;
  while(last<pages.length-1&&pages[last+1].title===title)last++;
  const rows=[];for(let i=first;i<=last;i++)pages[i].content.split('\n\n').forEach((text,n)=>rows.push({text,page:i,n}));
  return {title,first,last,rows,key:item.id+':'+first+':'+pages.length};
 },[pages,page,kind,item.id]);
 const base=kind==='pdf'?pdfSection:kind==='epub'?epubSection:section;
 const narrated=voiceSection&&base&&voiceSection.key!==base.key&&speaking?voiceSection:base;
 const byParagraph=script?segmentsByParagraph(script.segments):null;
 const paragraphIndex=useMemo(()=>new Map((narrated?.rows||[]).map((r,i)=>[r.page+':'+r.n,i])),[narrated?.key]);
 const language=useMemo(()=>{const sample=(narrated?.rows||[]).slice(0,40).map(r=>r.text).join(' ');return (sample.match(/[іїєґ]/gi)||[]).length>(sample.length/400)?'uk':'ru';},[narrated?.key]);
 function follow(row){
  const at=narrated?.rows[row.p];if(!at)return;
  const moved=speaking?.n!==at.n||speaking?.page!==at.page;
  setVoiceSection(narrated);setSpeaking({page:at.page,n:at.n,segment:row.segment});
  if(kind==='epub'){
   const node=epubNodes.current[at.n];if(!node)return;
   epubLast.current?.classList.remove('mv-speaking');node.classList.add('mv-speaking');epubLast.current=node;
   if(moved)try{view.current?.display(epubContents.current.cfiFromNode(node)).catch(()=>{});}catch{}
   return;
  }
  if(at.page!==page)setPage(at.page);
 }
 function nextSection(){
  if(kind==='epub'){const next=epub.current?.spine?.get((narrated?.sectionIndex??-1)+1);if(next){setVoiceSection(null);setSpeaking(null);setContinueVoice(true);view.current?.display(next.href).catch(()=>{});}return;}
  const next=(narrated?.last??page)+1;if(next<total){setVoiceSection(null);setSpeaking(null);setContinueVoice(true);setPage(next);}
 }
 function choose(n){setPage(Math.max(0,Math.min(total-1,n)));if(prefs.mode==='scroll')root.current?.querySelector('[data-book-page="'+n+'"]')?.scrollIntoView({behavior:'smooth',block:'start'});}
 const previous=()=>kind==='epub'?view.current?.prev().catch(e=>setError(e.message)):choose(page-1),next=()=>kind==='epub'?view.current?.next().catch(e=>setError(e.message)):choose(page+1);
 const options=<div className="reader-book-settings"><p className="reader-hint">Настрой один раз — параметры сохранятся для твоего профиля.</p><label className="narration-switch"><input type="checkbox" checked={prefs.roles} onChange={e=>update({roles:e.target.checked})}/>Показывать роли в тексте</label><label>Чтение<select aria-label="Режим чтения книги" value={prefs.mode} onChange={e=>update({mode:e.target.value})}><option value="pages">По страницам</option><option value="scroll">Непрерывная лента</option></select></label><label>Тема<select aria-label="Тема книги" value={prefs.theme} onChange={e=>update({theme:e.target.value})}><option value="paper">Бумага</option><option value="dark">Тёмная</option><option value="black">Чёрная · OLED</option></select></label>{kind!=='pdf'&&<><label>Шрифт<select aria-label="Шрифт книги" value={prefs.font} onChange={e=>update({font:e.target.value})}><option value="serif">Книжный</option><option value="sans">Без засечек</option></select></label><label>Размер текста<select aria-label="Размер текста книги" value={prefs.size} onChange={e=>update({size:Number(e.target.value)})}>{[16,18,20,22,24,28].map(v=><option key={v} value={v}>{v} px</option>)}</select></label><label>Интерлиньяж<select aria-label="Межстрочный интервал" value={prefs.lineHeight} onChange={e=>update({lineHeight:Number(e.target.value)})}>{[1.5,1.75,2].map(v=><option key={v} value={v}>{v}</option>)}</select></label></>}<label>Ширина<select aria-label="Ширина книги" value={prefs.width} onChange={e=>update({width:Number(e.target.value)})}>{[560,720,900,1100].map(v=><option key={v} value={v}>{v} px</option>)}</select></label></div>;
 const contents=<nav className="reader-chapter-list">{toc.length?toc.flatMap(function row(entry,i){return [<button key={entry.href||entry.index||i} translate="no" aria-current={entry.index===page} onClick={()=>entry.href?view.current?.display(entry.href).catch(e=>setError(e.message)):choose(entry.index)}>{entry.label}</button>,...(entry.subitems||[]).flatMap(row)];}):<p className="reader-empty">В файле нет отдельного оглавления.</p>}</nav>;
 const indices=prefs.mode==='scroll'?Array.from({length:total},(_,i)=>i):[page];
 const narration=!busy&&!error&&narrated?.rows.length>0?<Narration key={narrated.key} paragraphs={narrated.rows.map(r=>r.text)} language={language} bookKey={'book:'+item.id} chapterKey={narrated.key}
  title={item.name+(narrated.title?' · '+narrated.title:'')} book={{title:String(item.name||'').replace(/\.(epub|pdf|fb2|txt)$/i,''),kind:'book'}} service={service} userId={userId} startParagraph={Math.max(0,narrated.rows.findIndex(r=>r.page>=page))}
  autoplay={continueVoice} onAutoplayHandled={()=>setContinueVoice(false)}
  onSpeaking={follow} onFinished={nextSection} onScript={setScript} commandRef={voice} onPlaying={setVoicePlaying}/>
  :kind==='pdf'&&!busy&&!error?<p className="reader-rail-note" title="На этой странице нет текстового слоя"><Headphones size={16}/></p>:null;
 return <ReaderShell readerRef={root} title={item.name} subtitle={'Книга · '+extension.toUpperCase()} onClose={onClose} inline={inline} theme={prefs.theme} layout="rail" dock={narration} className="book-reader text-reader" paged={prefs.mode!=='scroll'} settings={options} settingsOpen={settings} onSettingsOpenChange={setSettings} contents={contents} progress={{current:total?page+1:0,total,label:kind==='epub'?epubLabel:total?(page+1)+' / '+total:'Открываем книгу…'}} onPage={kind==='epub'?undefined:choose} onPrevious={previous} onNext={next} canPrevious={!busy&&(kind==='epub'||page>0)} canNext={!busy&&(kind==='epub'||page<total-1)}>
  <div className={'book-reading-surface book-flow-'+prefs.mode} style={{'--book-width':prefs.width+'px','--book-font':prefs.font==='serif'?'Georgia,serif':'system-ui,sans-serif','--book-size':prefs.size+'px','--book-leading':prefs.lineHeight}} onScroll={e=>{if(prefs.mode!=='scroll'||!total||kind==='epub')return;const r=e.currentTarget.getBoundingClientRect(),elements=e.currentTarget.querySelectorAll('[data-book-page]');for(const element of elements){const rect=element.getBoundingClientRect();if(rect.top<=r.top+r.height*.35&&rect.bottom>r.top+r.height*.35){setPage(Number(element.dataset.bookPage));break;}}}}>
   {busy&&<div className="reader-book-loading" role="status">Открываем книгу…</div>}{error&&<p className="reader-book-error" role="alert">{error}</p>}
   <div className="reader-epub" ref={epubHost} style={{display:kind==='epub'?'block':'none'}}/>
   {!busy&&!error&&kind==='pdf'&&pdf.current&&indices.map(i=><PdfPage key={i} document={pdf.current} index={i} active={prefs.mode==='pages'} available={viewport} maxWidth={prefs.width}/>) }
   {!busy&&!error&&['txt','fb2'].includes(kind)&&indices.map(i=><article className={'reader-prose ranobe-prose'+(voicePlaying?' is-listening':'')} translate="no" data-book-page={i} key={i}>{pages[i]?.content.split('\n\n').map((p,n)=>{const at=paragraphIndex.get(i+':'+n),now=speaking?.page===i&&speaking.n===n;return <p key={n} className={now?'is-speaking':undefined}><RoleText text={p} segments={at!=null?byParagraph?.get(at):null} colors={script?.colors} speaking={now?speaking.segment:null} show={prefs.roles}/></p>;})}</article>)}
  </div>
 </ReaderShell>;
}
