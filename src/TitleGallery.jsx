import {useEffect,useId,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {X,ChevronLeft,ChevronRight,ZoomIn,ZoomOut,Maximize2,Film} from 'lucide-react';
import {useArtwork} from './title-artwork.js';
function GalleryImage({url,profile,actions,libraryId}){
 const src=useArtwork(url,profile,actions.readArtwork,libraryId),[failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[url]);
 return src&&!failed?<img src={src} alt="Открытый кадр" onError={()=>setFailed(true)} referrerPolicy="no-referrer"/>:<p role="status">{failed?'Источник не отдал изображение.':'Загружаем кадр…'}</p>;
}
export default function TitleGallery({images,profile,actions,libraryId,renderArtwork,manga=false}){
 const [index,setIndex]=useState(null),[zoom,setZoom]=useState(1),[error,setError]=useState(''),root=useRef(null),id=useId(),reduced=useReducedMotion();
 const move=delta=>setIndex(i=>(i+delta+images.length)%images.length);
 useEffect(()=>setZoom(1),[index]);
 async function full(){try{setError('');if(document.fullscreenElement)await document.exitFullscreen();else await root.current.requestFullscreen();}catch{setError('Браузер не разрешил полноэкранный режим.');}}
 return <section className="title-stills" id="titleStills"><div className="section-heading"><h2>{manga?'Страницы манги':'Кадры из аниме'}</h2><Film size={17}/></div><div className="title-horizontal gallery-thumbnails">{images.map((url,i)=><motion.button layoutId={reduced?undefined:id+':'+i} key={url} aria-label={'Открыть кадр '+(i+1)} onClick={()=>setIndex(i)}>{renderArtwork(url,i)}</motion.button>)}</div>
 <Dialog.Root open={index!==null} onOpenChange={open=>{if(!open)setIndex(null);}}><AnimatePresence>{index!==null&&<Dialog.Portal forceMount><Dialog.Overlay forceMount asChild><motion.div className="dialog-overlay gallery-backdrop" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}/></Dialog.Overlay><Dialog.Content forceMount asChild onKeyDown={event=>{if(event.key==='ArrowRight'){event.preventDefault();move(1);}if(event.key==='ArrowLeft'){event.preventDefault();move(-1);}}} onEscapeKeyDown={event=>{if(document.fullscreenElement){event.preventDefault();document.exitFullscreen().catch(()=>{});}}}><motion.div ref={root} className="gallery-dialog gallery-minimal" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduced?0:.2}}>
 <header><Dialog.Title className="sr-only">Кадр {index+1} / {images.length}</Dialog.Title><Dialog.Description className="sr-only">{profile.title||'Изображения тайтла'}</Dialog.Description><span>{index+1} / {images.length}</span><div className="entity-dialog-actions"><button aria-label="Уменьшить кадр" disabled={zoom<=1} onClick={()=>setZoom(z=>Math.max(1,z-.5))}><ZoomOut size={18}/></button><button aria-label="Увеличить кадр" disabled={zoom>=3} onClick={()=>setZoom(z=>Math.min(3,z+.5))}><ZoomIn size={18}/></button><button aria-label="Кадр на весь экран" onClick={full}><Maximize2 size={18}/></button><Dialog.Close aria-label="Закрыть кадр"><X size={20}/></Dialog.Close></div></header>
 <div className="gallery-viewport"><motion.div layoutId={reduced?undefined:id+':'+index} className="gallery-image-surface" style={{width:zoom*100+'%',height:zoom*100+'%'}} transition={{type:'spring',stiffness:300,damping:32}}><GalleryImage url={images[index]} profile={profile} actions={actions} libraryId={libraryId}/></motion.div></div>
 <button className="gallery-previous" aria-label="Предыдущий кадр" onClick={()=>move(-1)}><ChevronLeft size={24}/></button><button className="gallery-next" aria-label="Следующий кадр" onClick={()=>move(1)}><ChevronRight size={24}/></button>{error&&<p className="gallery-error" role="status">{error}</p>}
 </motion.div></Dialog.Content></Dialog.Portal>}</AnimatePresence></Dialog.Root></section>;
}
