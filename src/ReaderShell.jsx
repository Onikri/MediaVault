import {useCallback,useEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {ArrowLeft,ChevronLeft,ChevronRight,Settings2,Maximize,Minimize,List,Grid2X2,X} from 'lucide-react';
import './reader-shell.css';

// Chrome overlays the reading surface. Opening a panel never resizes a page.
export default function ReaderShell({readerRef,title,subtitle,onClose,children,settings,settingsOpen=false,onSettingsOpenChange,contents,previews,actions,progress,onPage,onPrevious,onNext,canPrevious=true,canNext=true,paged=true,direction='ltr',theme='dark',inline=false,embedded=false,className='',chromeWidth=1200,status}){
 const local=useRef(null),root=readerRef||local,timer=useRef(null),gesture=useRef(null),methods=useRef({});
 const [visible,setVisible]=useState(false),[panel,setPanel]=useState(''),[full,setFull]=useState(false),[hint,setHint]=useState(true),[fullscreenError,setFullscreenError]=useState('');
 methods.current={onClose,onPrevious,onNext,canPrevious,canNext,paged,direction,settingsOpen,panel};
 const hide=useCallback(()=>{clearTimeout(timer.current);setVisible(false);},[]);
 const show=useCallback(()=>{clearTimeout(timer.current);setVisible(true);timer.current=setTimeout(()=>{if(!root.current?.querySelector('.reader-chrome:focus-within'))setVisible(false);},2800);},[]);
 const closePanel=()=>{setPanel('');onSettingsOpenChange?.(false);show();};
 const openPanel=value=>{show();setPanel(value==='settings'?'':value);onSettingsOpenChange?.(value==='settings');};
 const activePanel=settingsOpen?'settings':panel;
 useEffect(()=>{setVisible(false);setHint(true);const t=setTimeout(()=>setHint(false),3200);return()=>clearTimeout(t);},[title]);
 useEffect(()=>{const previous=document.body.style.overflow;if(!inline)document.body.style.overflow='hidden';const locked=()=>methods.current.onClose?.();addEventListener('mediavault-locked',locked);return()=>{clearTimeout(timer.current);if(!inline)document.body.style.overflow=previous;removeEventListener('mediavault-locked',locked);};},[inline]);
 useEffect(()=>{const node=root.current,toggle=()=>node?.dataset.chrome==='true'?hide():show();node?.addEventListener('reader-toggle-chrome',toggle);node?.addEventListener('reader-show-chrome',show);return()=>{node?.removeEventListener('reader-toggle-chrome',toggle);node?.removeEventListener('reader-show-chrome',show);};},[show,hide]);
 useEffect(()=>{const update=()=>setFull(document.fullscreenElement===root.current);document.addEventListener('fullscreenchange',update);return()=>document.removeEventListener('fullscreenchange',update);},[]);
 async function fullscreen(){setFullscreenError('');try{if(document.fullscreenElement)await document.exitFullscreen();else if(root.current?.requestFullscreen)await root.current.requestFullscreen();else setFullscreenError('Используется полноэкранный режим читалки.');}catch{setFullscreenError('Браузер не разрешил системный полноэкранный режим.');}}
 useEffect(()=>{const key=e=>{
  const m=methods.current,dialog=document.activeElement?.closest('[role="dialog"]');
  if(embedded&&!root.current?.contains(document.activeElement)&&document.fullscreenElement!==root.current&&!document.fullscreenElement?.contains(root.current))return;
  if(e.defaultPrevented||e.target.closest?.('input,textarea,select,[contenteditable=true]')||dialog&&dialog!==root.current&&!dialog.contains(root.current)||m.settingsOpen||m.panel)return;
  if(e.key==='Tab'&&!embedded){
   if(!visible){e.preventDefault();show();requestAnimationFrame(()=>root.current?.querySelector('.reader-top button')?.focus());return;}
   const controls=[...root.current.querySelectorAll('button:not(:disabled),input:not(:disabled),a[href]')].filter(node=>!node.closest('[inert]')&&node.getClientRects().length);
   const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}return;
  }
  if(e.key==='Escape'){e.preventDefault();if(visible)hide();else m.onClose?.();return;}
  if(e.key.toLowerCase()==='f'){e.preventDefault();fullscreen();return;}
  if(m.paged&&['ArrowLeft','ArrowRight',' '].includes(e.key)){
   e.preventDefault();const delta=e.key===' '?1:(e.key==='ArrowRight'?1:-1)*(m.direction==='rtl'?-1:1);
   if(delta>0&&m.canNext)m.onNext?.();if(delta<0&&m.canPrevious)m.onPrevious?.();hide();
  }
 };addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[visible,show,hide,embedded]);
 function pointerDown(e){
  if(!e.isPrimary||e.button>0||e.target.closest('button,a,input,select,textarea,[role="button"]')){gesture.current=null;return;}
  if(embedded)root.current?.focus({preventScroll:true});
  gesture.current={x:e.clientX,y:e.clientY,time:performance.now(),pointer:e.pointerType};
 }
 function pointerUp(e){
  const start=gesture.current;gesture.current=null;if(!start||activePanel||performance.now()-start.time>400||getSelection()?.toString())return;
  const dx=e.clientX-start.x,dy=e.clientY-start.y;if(Math.abs(dy)>35)return;
  if(paged&&Math.abs(dx)>60){const forward=(dx<0)===(direction!=='rtl');if(forward&&canNext)onNext?.();if(!forward&&canPrevious)onPrevious?.();hide();return;}
  if(Math.abs(dx)>12||Math.abs(dy)>12)return;
  if(paged){const bounds=e.currentTarget.getBoundingClientRect(),fraction=(e.clientX-bounds.left)/bounds.width;if(fraction<.26||fraction>.74){const forward=(fraction>.74)===(direction!=='rtl');if(forward&&canNext)onNext?.();if(!forward&&canPrevious)onPrevious?.();hide();return;}}
  setHint(false);visible?hide():show();
 }
 return <section id="viewer" ref={root} tabIndex={-1} className={'mv-viewer immersive-reader reader-theme-'+theme+' '+className+(inline?' mv-viewer-inline':'')+(embedded?' reader-embedded':'')} style={{'--reader-chrome-width':Math.max(320,Math.min(1800,Number(chromeWidth)||1200))+'px'}} data-chrome={visible||!!activePanel} role={inline?'region':'dialog'} aria-modal={inline?undefined:'true'} aria-label={title}>
  <div className="immersive-stage" onPointerDown={pointerDown} onPointerUp={pointerUp} onPointerCancel={()=>gesture.current=null} onPointerMove={e=>{if(e.pointerType==='mouse'&&!e.buttons){const r=e.currentTarget.getBoundingClientRect();if(e.clientY-r.top<65||r.bottom-e.clientY<65)show();}}}>{children}</div>
  <div className="reader-chrome reader-top" inert={!visible&&!activePanel} onPointerEnter={()=>clearTimeout(timer.current)} onPointerLeave={show} onFocusCapture={()=>clearTimeout(timer.current)} onBlurCapture={show}>
   <button className="reader-control" aria-label="Закрыть просмотр" onClick={onClose}><ArrowLeft size={20}/></button>
   <div className="mv-viewer-title"><small>{subtitle}</small><strong>{title}</strong></div>
   <div className="reader-top-actions">{actions}<button className="reader-control reader-fullscreen" aria-label={full?'Выйти из полного экрана':'На весь экран'} onClick={fullscreen}>{full?<Minimize size={19}/>:<Maximize size={19}/>}</button>{settings&&<button className="reader-control" aria-label="Настройки читалки" aria-expanded={settingsOpen} onClick={()=>openPanel('settings')}><Settings2 size={20}/></button>}</div>
  </div>
  <div className="reader-chrome reader-bottom reader-bottom-float mv-viewer-tools" inert={!visible&&!activePanel} onPointerEnter={()=>clearTimeout(timer.current)} onPointerLeave={show} onFocusCapture={()=>clearTimeout(timer.current)} onBlurCapture={show}>
   <div className="reader-navigation">{contents&&<button className="reader-control" aria-label="Главы и тома" onClick={()=>openPanel('contents')}><List size={20}/></button>}{previews&&<button className="reader-control" aria-label="Превью страниц" onClick={()=>openPanel('previews')}><Grid2X2 size={19}/></button>}
    <button className="reader-control" aria-label="Назад" disabled={!canPrevious} onClick={onPrevious}><ChevronLeft size={22}/></button>
    <span className="reader-page-count" aria-live="polite">{progress?.label||`${progress?.current||0} / ${progress?.total||0}`}</span>
    <button className="reader-control" aria-label="Вперёд" disabled={!canNext} onClick={onNext}><ChevronRight size={22}/></button>
   </div>
   {onPage&&progress?.total>1&&<input className="reader-progress-slider" type="range" aria-label="Перейти к странице" min="1" max={progress.total} value={Math.min(progress.total,progress.current||1)} onChange={e=>onPage(Number(e.target.value)-1)}/>}
   {status&&<div className="reader-quiet-status">{status}</div>}{fullscreenError&&<small role="status">{fullscreenError}</small>}
  </div>
  {hint&&!visible&&!activePanel&&<div className="reader-gesture-hint" aria-hidden="true">Касание центра — меню{paged?' · По краям — листать':''}</div>}
  <Dialog.Root open={!!activePanel} onOpenChange={open=>!open&&closePanel()}><Dialog.Portal container={full?root.current:undefined}><Dialog.Overlay className="reader-panel-backdrop"/><Dialog.Content className={'reader-panel reader-panel-'+activePanel} data-reader-panel onCloseAutoFocus={e=>{e.preventDefault();root.current?.focus({preventScroll:true});}}>
   <header><div><small>Твоё пространство для чтения</small><Dialog.Title>{activePanel==='settings'?'Настройки читалки':activePanel==='contents'?'Главы и тома':'Превью страниц'}</Dialog.Title></div><Dialog.Close className="reader-control" aria-label={activePanel==='settings'?'Закрыть настройки читалки':'Закрыть панель читалки'}><X size={20}/></Dialog.Close></header>
   <Dialog.Description className="sr-only">Настройки и навигация. Закрой панель, чтобы вернуться к чтению.</Dialog.Description>
   <div className="reader-panel-body" onClick={e=>{if(activePanel!=='settings'&&e.target.closest('button'))closePanel();}}>{activePanel==='settings'?settings:activePanel==='contents'?contents:previews}</div>
  </Dialog.Content></Dialog.Portal></Dialog.Root>
 </section>;
}
