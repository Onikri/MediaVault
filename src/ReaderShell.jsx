import ReaderPageTrack from './ReaderPageTrack.jsx';
import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowLeft,ChevronDown,ChevronLeft,ChevronRight,ChevronUp,Settings2,Maximize,Minimize,Minimize2,List,Grid2X2,X} from 'lucide-react';
import './reader-shell.css';
import './reader-morph.css';
import './reader-rail.css';
import './reader-status.css';
import './reader-chrome.css';

const ZONES_SEEN='mv_reader_zones_v1';
const sheetSpring={type:'spring',stiffness:380,damping:38,mass:.9};
// Where a tap lands. Paged modes: left and right edges turn pages. A
// continuous webtoon: top and bottom edges scroll by a screen. The middle
// always opens the menu.
export function readerZone(fx,fy,{paged,scroll}){
 if(paged){if(fx<.3)return 'left';if(fx>.7)return 'right';return 'center';}
 if(scroll){if(fy<.28)return 'top';if(fy>.72)return 'bottom';}
 return 'center';
}
function zoneLabels(paged,navigation){
 if(!paged)return {top:'Прокрутить вверх',center:'Меню',bottom:'Прокрутить вниз'};
 const forward=navigation==='rtl'?'left':'right';
 return {left:forward==='left'?'Следующая страница':'Предыдущая страница',center:'Меню',right:forward==='right'?'Следующая страница':'Предыдущая страница'};
}
const zoneIcon={left:ChevronLeft,right:ChevronRight,top:ChevronUp,bottom:ChevronDown};

// Chrome overlays the reading surface. Opening a panel never resizes a page.
// layout="rail" (text readers): one fixed column of controls on the right,
// always visible — nothing appears on hover, so nothing moves under the
// pointer. dock (the narration player) sits at the bottom of the rail;
// onMinimize hides the reader to the tray while its voice keeps reading.
export default function ReaderShell({readerRef,title,subtitle,onClose,children,settings,settingsOpen=false,onSettingsOpenChange,contents,previews,actions,progress,onPage,onPrevious,onNext,canPrevious=true,canNext=true,paged=true,direction='ltr',theme='dark',inline=false,embedded=false,className='',chromeWidth=1200,status,debug,readingMode,onReadingMode,progressOrientation='vertical',navigationDirection='reading',chapterControl,gesturesEnabled=true,layout='overlay',dock=null,onMinimize,navigationLabels,pagePreview,statusWide=false,onStep,zoneGuide=0}){
 const local=useRef(null),root=readerRef||local,timer=useRef(null),gesture=useRef(null),methods=useRef({}),stage=useRef(null);
 const rail=layout==='rail',reduce=useReducedMotion();
 const [visible,setVisible]=useState(false),[panel,setPanel]=useState(''),[full,setFull]=useState(false),[fullscreenError,setFullscreenError]=useState(''),[zone,setZone]=useState(''),[guide,setGuide]=useState(false),[sheet,setSheet]=useState(false),[portal,setPortal]=useState(null);
 methods.current={onClose,onMinimize,onPrevious,onNext,canPrevious,canNext,paged,direction,settingsOpen,panel,rail};
 const navigation=navigationDirection==='reading'?direction:navigationDirection==='left'?'rtl':'ltr';methods.current.direction=navigation;
 const hide=useCallback(()=>{clearTimeout(timer.current);setVisible(false);},[]);
 const show=useCallback(()=>{clearTimeout(timer.current);setVisible(true);timer.current=setTimeout(()=>{if(!root.current?.querySelector('.reader-chrome:focus-within'))setVisible(false);},2800);},[]);
 const closePanel=()=>{setPanel('');onSettingsOpenChange?.(false);show();};
 const openPanel=value=>{show();setPanel(value==='settings'?'':value);onSettingsOpenChange?.(value==='settings');};
 const activePanel=settingsOpen?'settings':panel,shownPanel=useRef(activePanel);if(activePanel)shownPanel.current=activePanel;
 // The tap map shows once per device, and again from «Показать зоны касания».
 useEffect(()=>{if(rail)return;let seen=false;try{seen=localStorage.getItem(ZONES_SEEN)==='1';}catch{}setVisible(false);if(!seen){setGuide(true);try{localStorage.setItem(ZONES_SEEN,'1');}catch{}}},[title,rail]);
 useEffect(()=>{if(zoneGuide&&!rail)setGuide(true);},[zoneGuide,rail]);
 useEffect(()=>{if(!guide)return;const t=setTimeout(()=>setGuide(false),activePanel?2200:3400);return()=>clearTimeout(t);},[guide,activePanel]);
 useLayoutEffect(()=>{setPortal(root.current);const node=root.current;if(!node)return;const observer=new ResizeObserver(()=>setSheet(node.getBoundingClientRect().width<600));observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>{const previous=document.body.style.overflow;if(!inline)document.body.style.overflow='hidden';const locked=()=>methods.current.onClose?.();addEventListener('mediavault-locked',locked);return()=>{clearTimeout(timer.current);if(!inline)document.body.style.overflow=previous;removeEventListener('mediavault-locked',locked);};},[inline]);
 useEffect(()=>{const node=root.current,toggle=()=>node?.dataset.chrome==='true'?hide():show();node?.addEventListener('reader-toggle-chrome',toggle);node?.addEventListener('reader-show-chrome',show);return()=>{node?.removeEventListener('reader-toggle-chrome',toggle);node?.removeEventListener('reader-show-chrome',show);};},[show,hide]);
 // Entering or leaving full screen eases the page in instead of snapping.
 useEffect(()=>{const update=()=>{const now=document.fullscreenElement===root.current;setFull(now);if(!reduce&&stage.current?.animate&&(now||root.current?.contains(document.activeElement)||!document.fullscreenElement))stage.current.animate([{opacity:.25,transform:'scale(.985)'},{opacity:1,transform:'none'}],{duration:460,easing:'cubic-bezier(.22,1,.36,1)'});};document.addEventListener('fullscreenchange',update);return()=>document.removeEventListener('fullscreenchange',update);},[reduce]);
 async function fullscreen(){setFullscreenError('');try{if(document.fullscreenElement)await document.exitFullscreen();else if(root.current?.requestFullscreen)await root.current.requestFullscreen();else setFullscreenError('Используется полноэкранный режим читалки.');}catch{setFullscreenError('Браузер не разрешил системный полноэкранный режим.');}}
 useEffect(()=>{const key=e=>{
  const m=methods.current,dialog=document.activeElement?.closest('[role="dialog"]');
  if(embedded&&!root.current?.contains(document.activeElement)&&document.fullscreenElement!==root.current&&!document.fullscreenElement?.contains(root.current))return;
  if(e.defaultPrevented||e.target.closest?.('input,textarea,select,[contenteditable=true]')||dialog&&dialog!==root.current&&!dialog.contains(root.current)||m.settingsOpen||m.panel)return;
  if(e.key==='Tab'&&!embedded){
   if(!visible&&!m.rail){e.preventDefault();show();requestAnimationFrame(()=>root.current?.querySelector('.reader-top button')?.focus());return;}
   const controls=[...root.current.querySelectorAll('button:not(:disabled),input:not(:disabled),a[href]')].filter(node=>!node.closest('[inert]')&&node.getClientRects().length);
   const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}return;
  }
  if(e.key==='Escape'){e.preventDefault();if(m.rail)(m.onMinimize||m.onClose)?.();else if(visible)hide();else m.onClose?.();return;}
  if(e.key.toLowerCase()==='f'){e.preventDefault();fullscreen();return;}
  if(m.paged&&['ArrowLeft','ArrowRight',' '].includes(e.key)){
   e.preventDefault();const delta=e.key===' '?1:(e.key==='ArrowRight'?1:-1)*(m.direction==='rtl'?-1:1);
   if(delta>0&&m.canNext)m.onNext?.();if(delta<0&&m.canPrevious)m.onPrevious?.();hide();
  }
 };addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[visible,show,hide,embedded]);
 const zoneOf=(e,bounds=stage.current?.getBoundingClientRect())=>bounds?readerZone((e.clientX-bounds.left)/bounds.width,(e.clientY-bounds.top)/bounds.height,{paged:paged&&gesturesEnabled,scroll:!paged&&!!onStep}):'center';
 function pointerDown(e){
  if(guide)setGuide(false);
  if(!e.isPrimary||e.button>0||e.target.closest('button,a,input,select,textarea,[role="button"]')){gesture.current=null;return;}
  if(embedded)root.current?.focus({preventScroll:true});
  gesture.current={x:e.clientX,y:e.clientY,time:performance.now(),pointer:e.pointerType};
 }
 function pointerUp(e){
  const start=gesture.current;gesture.current=null;if(!start||activePanel||performance.now()-start.time>400||getSelection()?.toString())return;
  const dx=e.clientX-start.x,dy=e.clientY-start.y;
  if(paged&&gesturesEnabled&&Math.abs(dx)>60&&Math.abs(dy)<=35){const forward=(dx<0)===(navigation!=='rtl');if(forward&&canNext)onNext?.();if(!forward&&canPrevious)onPrevious?.();hide();return;}
  if(Math.abs(dx)>12||Math.abs(dy)>12)return;
  const at=zoneOf(e);
  if(at==='left'||at==='right'){const forward=(at==='right')===(navigation!=='rtl');if(forward&&canNext)onNext?.();if(!forward&&canPrevious)onPrevious?.();hide();return;}
  if(at==='top'||at==='bottom'){onStep?.(at==='top'?-1:1);hide();return;}
  if(rail)return;
  visible?hide():show();
 }
 function pointerMove(e){
  if(rail||e.pointerType!=='mouse'||e.buttons)return;
  const r=e.currentTarget.getBoundingClientRect(),next=zoneOf(e,r);if(next!==zone)setZone(next);
  if(e.clientY-r.top<65||r.right-e.clientX<84)show();
 }
 const labels=zoneLabels(paged,navigation),HoverIcon=zoneIcon[zone];
 const hoverEnabled=zone&&zone!=='center'&&!activePanel&&!guide&&(paged?(zone==='left'?canPrevious||canNext:true):!!onStep);
 const forwardSide=navigation==='rtl'?'left':'right';
 const sideEnabled=side=>paged?(side===forwardSide?canNext:canPrevious):true;
 // Text readers keep their full-window panel; the manga reader's panel slides out of the reader itself.
 const container=rail?(full?root.current:typeof document==='undefined'?null:document.body):portal;
 const panelTitle={settings:'Настройки читалки',contents:'Главы и тома',previews:'Страницы главы'}[shownPanel.current]||'Читалка';
 return <section id="viewer" ref={root} tabIndex={-1} className={'mv-viewer immersive-reader'+(progressOrientation==='vertical'?' reader-vertical-tools':'')+' reader-theme-'+theme+' '+className+(inline?' mv-viewer-inline':'')+(embedded?' reader-embedded':'')+(full?' is-fullscreen':'')} style={{'--reader-chrome-width':Math.max(320,Math.min(1800,Number(chromeWidth)||1200))+'px'}} data-chrome={rail||visible||!!activePanel} data-layout={layout} data-panel={activePanel||undefined} role={inline?'region':'dialog'} aria-modal={inline?undefined:'true'} aria-label={title}>
  <div ref={stage} className="immersive-stage" onPointerDown={pointerDown} onPointerUp={pointerUp} onPointerCancel={()=>gesture.current=null} onPointerMove={pointerMove} onPointerLeave={()=>setZone('')}>{children}</div>
  {rail?<aside className="reader-rail" aria-label="Управление читалкой">
   <div className="reader-rail-group">
    <button className="reader-control" aria-label="Закрыть читалку" title="Закрыть" onClick={onClose}><X size={19}/></button>
    {onMinimize&&<button className="reader-control" aria-label="Свернуть читалку" title="Свернуть — голос продолжит читать" onClick={onMinimize}><Minimize2 size={18}/></button>}
    {contents&&<button className="reader-control" aria-label="Главы и тома" title="Оглавление" onClick={()=>openPanel('contents')}><List size={19}/></button>}
    {settings&&<button className="reader-control" aria-label="Настройки читалки" title="Текст и тема" aria-expanded={settingsOpen} onClick={()=>openPanel('settings')}><Settings2 size={19}/></button>}
    <button className="reader-control reader-fullscreen" aria-label={full?'Выйти из полного экрана':'На весь экран'} title={full?'Обычный размер':'На весь экран'} onClick={fullscreen}>{full?<Minimize size={18}/>:<Maximize size={18}/>}</button>
   </div>
   <div className="reader-rail-group reader-rail-pages">
    <button className="reader-control" aria-label={navigationLabels?.previous||'Назад'} title={navigationLabels?.previous||'Назад'} disabled={!canPrevious} onClick={onPrevious}><ChevronLeft size={20}/></button>
    <span className="reader-rail-count" aria-live="polite" title={progress?.label}>{progress?.current||0}<small>из {progress?.total||0}</small></span>
    <button className="reader-control" aria-label={navigationLabels?.next||'Вперёд'} title={navigationLabels?.next||'Вперёд'} disabled={!canNext} onClick={onNext}><ChevronRight size={20}/></button>
   </div>
   {dock&&<div className="reader-rail-dock">{dock}</div>}
   {fullscreenError&&<small className="reader-rail-note" role="status">{fullscreenError}</small>}
  </aside>:<>
  {/* Edge under the mouse: what a click there does. */}
  <AnimatePresence>{hoverEnabled&&HoverIcon&&<motion.div key={zone} className="reader-zone-hover" data-zone={zone} data-disabled={(paged&&!sideEnabled(zone))||undefined} aria-hidden="true" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduce?0:.18}}><span><HoverIcon size={22}/><small>{labels[zone]}</small></span></motion.div>}</AnimatePresence>
  <AnimatePresence>{guide&&<motion.div key="guide" className={'reader-zone-guide '+(paged?'is-paged':'is-scroll')} aria-hidden="true" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduce?0:.28}}>
   {(paged?['left','center','right']:['top','center','bottom']).map((side,index)=>{const Icon=zoneIcon[side];return <motion.div key={side} data-zone={side} initial={reduce?{opacity:0}:{opacity:0,scale:.96}} animate={{opacity:1,scale:1}} transition={reduce?{duration:0}:{delay:.06*index,type:'spring',stiffness:300,damping:30}}><span>{Icon&&<Icon size={22}/>}<strong>{labels[side]}</strong>{side==='center'&&<small>Касание по центру</small>}</span></motion.div>;})}
  </motion.div>}</AnimatePresence>
  <div className="reader-chrome reader-top" inert={!visible&&!activePanel} onPointerEnter={()=>clearTimeout(timer.current)} onPointerLeave={show} onFocusCapture={()=>clearTimeout(timer.current)} onBlurCapture={show}>
   <button className="reader-control" aria-label="Закрыть просмотр" title="Закрыть" onClick={onClose}><ArrowLeft size={20}/></button>
   <div className="reader-title-group"><div className="mv-viewer-title"><strong>{title}</strong></div>{chapterControl}</div>
   <div className="reader-top-actions">{previews&&<button className="reader-control" aria-label="Превью страниц" title="Страницы главы" onClick={()=>openPanel('previews')}><Grid2X2 size={19}/></button>}{contents&&<button className="reader-control" aria-label="Главы и тома" title="Главы и тома" onClick={()=>openPanel('contents')}><List size={20}/></button>}{actions}<button className="reader-control reader-fullscreen" aria-label={full?'Выйти из полного экрана':'На весь экран'} title={full?'Выйти из полного экрана':'На весь экран'} onClick={fullscreen}>{full?<Minimize size={19}/>:<Maximize size={19}/>}</button>{settings&&<button className="reader-control" aria-label="Настройки читалки" title="Настройки читалки" aria-expanded={settingsOpen} onClick={()=>openPanel('settings')}><Settings2 size={20}/></button>}</div>
  </div>
  <nav className="reader-chrome reader-pager" aria-label="Страницы главы" inert={!visible&&!activePanel} onPointerEnter={()=>clearTimeout(timer.current)} onPointerLeave={show} onFocusCapture={()=>clearTimeout(timer.current)} onBlurCapture={show}>
   <button className="reader-control" aria-label="Назад" title="Предыдущая страница" disabled={!canPrevious} onClick={onPrevious}><ChevronUp size={22}/></button>
   {onPage&&progress?.total>1?<ReaderPageTrack progress={progress} onPage={onPage} orientation="vertical" chapter={title} preview={pagePreview}/>:<span className="reader-page-count" aria-live="polite"><strong>{progress?.current||0}</strong>{' '}<small>из {progress?.total||0}</small></span>}
   <button className="reader-control" aria-label="Вперёд" title="Следующая страница" disabled={!canNext} onClick={onNext}><ChevronDown size={22}/></button>
  </nav>
  {fullscreenError&&<small className="reader-fullscreen-note" role="status">{fullscreenError}</small>}
  {/* Page status lives in its own floating chip, never inside the page track. */}
  <AnimatePresence>{status&&<motion.div key="status" className={'reader-status-dock'+(statusWide?' is-wide':'')} layout={!reduce} initial={{opacity:0,y:10,scale:.96}} animate={{opacity:1,y:0,scale:1}} exit={{opacity:0,y:8,scale:.97,transition:{duration:.16}}} transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:34}}>{status}</motion.div>}</AnimatePresence>
  </>}
  {debug}
  <Dialog.Root open={!!activePanel} onOpenChange={open=>!open&&closePanel()}>
   <AnimatePresence>{activePanel&&container&&<Dialog.Portal forceMount container={container}>
    <Dialog.Overlay asChild forceMount><motion.div className="reader-panel-backdrop" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduce?0:.22}}/></Dialog.Overlay>
    <Dialog.Content asChild forceMount data-reader-panel onCloseAutoFocus={e=>{e.preventDefault();root.current?.focus({preventScroll:true});}}>
     <motion.div className={'reader-panel reader-panel-'+shownPanel.current+(sheet?' is-sheet':'')} initial={reduce?{opacity:0}:sheet?{y:'104%'}:{x:'calc(100% + 28px)'}} animate={reduce?{opacity:1}:sheet?{y:0}:{x:0}} exit={reduce?{opacity:0}:sheet?{y:'104%'}:{x:'calc(100% + 28px)'}} transition={reduce?{duration:.12}:sheetSpring}>
      <header><Dialog.Title>{panelTitle}</Dialog.Title><Dialog.Close className="reader-control" aria-label={shownPanel.current==='settings'?'Закрыть настройки читалки':'Закрыть панель читалки'}><X size={20}/></Dialog.Close></header>
      <Dialog.Description className="sr-only">Настройки и навигация. Закрой панель, чтобы вернуться к чтению.</Dialog.Description>
      <div className="reader-panel-body" onClick={e=>{if(shownPanel.current!=='settings'&&e.target.closest('button'))closePanel();}}>{shownPanel.current==='settings'?settings:shownPanel.current==='contents'?contents:previews}</div>
     </motion.div>
    </Dialog.Content>
   </Dialog.Portal>}</AnimatePresence>
  </Dialog.Root>
 </section>;
}
