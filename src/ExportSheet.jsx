import {useEffect,useRef} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Download,X} from 'lucide-react';
import UiSegmented from './UiSegmented.jsx';
import './export-sheet.css';

export const DESTINATIONS=[['local','На устройство'],['drive','В Google Диск']];
// One save window for every kind of title. It is not modal, like the player
// and reader mini-apps: the page keeps scrolling and answering clicks while it
// is open, and a running save survives closing it. Escape or × closes it.
export default function ExportSheet({open,onOpenChange,title,subtitle,destination,onDestination,destinations=DESTINATIONS,children,trigger}){
 const reduce=useReducedMotion(),body=useRef(null);
 useEffect(()=>{if(open)body.current?.scrollTo?.({top:0});},[open,destination]);
 return <Dialog.Root open={open} onOpenChange={onOpenChange} modal={false}>
  {trigger}
  <AnimatePresence>{open&&<Dialog.Portal forceMount>
   <Dialog.Content forceMount asChild aria-describedby={undefined}
    onInteractOutside={event=>event.preventDefault()}
    onOpenAutoFocus={event=>{event.preventDefault();event.currentTarget?.focus?.({preventScroll:true});}}>
    <motion.section className="export-sheet" tabIndex={-1}
     initial={reduce?{opacity:0}:{opacity:0,y:18,scale:.98}} animate={{opacity:1,y:0,scale:1}} exit={reduce?{opacity:0}:{opacity:0,y:12,scale:.98}}
     transition={reduce?{duration:.12}:{type:'spring',stiffness:420,damping:36}}>
     <header className="export-sheet-head">
      <div><Dialog.Title>{title}</Dialog.Title>{subtitle&&<p>{subtitle}</p>}</div>
      <Dialog.Close className="export-sheet-close" aria-label="Закрыть окно сохранения"><X size={17}/></Dialog.Close>
     </header>
     {destinations.length>1&&<UiSegmented className="export-sheet-destination is-wide" label="Куда сохранить" value={destination} options={destinations} onChange={onDestination}/>}
     <div className="export-sheet-body" ref={body}>{children}</div>
    </motion.section>
   </Dialog.Content>
  </Dialog.Portal>}</AnimatePresence>
 </Dialog.Root>;
}

export function ExportTrigger({label='Сохранить'}){
 return <Dialog.Trigger className="circle-button export-trigger" aria-label={label} title={label}><Download size={17}/></Dialog.Trigger>;
}
