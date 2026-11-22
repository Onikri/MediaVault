import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ChevronLeft, ChevronRight, Maximize2, X, ZoomIn, ZoomOut} from 'lucide-react';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, ease, glass, useEntered} from './ui.jsx';

/* Кадры: the mosaic rises tile by tile; the viewer is a dark film room: the
   frame slides with depth, a filmstrip follows below and one glass control
   pill holds the counter, zoom and fullscreen. */
function FilmViewer({images, index, setIndex, isNoir, renderArtwork, caption}) {
  const [dir, setDir] = useState(1), [zoom, setZoom] = useState(false), strip = useRef(null), root = useRef(null), reduce = useReducedMotion();
  const count = images.length;
  const go = d => { setDir(d); setZoom(false); setIndex(i => (i + d + count) % count); };
  const goRef = useRef(go); goRef.current = go;
  useEffect(() => {
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); setIndex(null); } if (e.key === 'ArrowRight') goRef.current(1); if (e.key === 'ArrowLeft') goRef.current(-1); };
    addEventListener('keydown', key);
    root.current?.querySelector('[aria-label="Закрыть кадры"]')?.focus({preventScroll: true});
    return () => { removeEventListener('keydown', key); if (document.fullscreenElement === root.current) document.exitFullscreen?.().catch(() => {}); };
  }, []);
  useEffect(() => { const box = strip.current, on = box?.querySelector(`[data-i="${index}"]`); if (box && on) box.scrollTo({left: on.offsetLeft - (box.clientWidth - on.offsetWidth) / 2, behavior: reduce ? 'auto' : 'smooth'}); }, [index]);
  const button = 'w-9 h-9 grid place-items-center rounded-full text-zinc-300 hover:text-white hover:bg-white/10';
  return <motion.div ref={root} className="fixed inset-0 flex flex-col bg-black/95 backdrop-blur-2xl" style={{zIndex: 1250}} initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} role="dialog" aria-modal="true" aria-label="Кадры">
    <div className="relative flex-1 min-h-0 flex items-center justify-center overflow-hidden px-4 sm:px-20 pt-16 pb-4">
      <AnimatePresence mode="popLayout" initial={false} custom={dir}>
        <motion.div key={index} custom={dir} className={`relative w-full max-w-6xl max-h-full aspect-video rounded-[28px] overflow-hidden shadow-[0_40px_120px_-20px_rgba(0,0,0,0.9)] border border-white/[0.08] bg-white/[0.03] ${isNoir ? 'grayscale' : ''}`}
          variants={{enter: d => ({x: d * 120, opacity: 0, scale: .92, filter: 'blur(8px)'}), center: {x: 0, opacity: 1, scale: 1, filter: 'blur(0px)'}, exit: d => ({x: d * -120, opacity: 0, scale: .96, filter: 'blur(6px)'})}}
          initial={reduce ? false : 'enter'} animate="center" exit="exit" transition={{duration: reduce ? 0 : .55, ease}}>
          <motion.div className={`absolute inset-0 kt-cover kt-contain ${zoom ? 'cursor-zoom-out' : 'cursor-zoom-in'}`} animate={{scale: zoom ? 1.6 : 1}} transition={{duration: reduce ? 0 : .6, ease}} onClick={() => setZoom(z => !z)}>{renderArtwork(images[index], index)}</motion.div>
          <span className="absolute left-6 bottom-5 text-sm font-semibold text-white drop-shadow-[0_2px_10px_rgba(0,0,0,0.8)] pointer-events-none">{caption} {index + 1}</span>
        </motion.div>
      </AnimatePresence>
      {count > 1 && <>
        <button type="button" aria-label="Предыдущий кадр" onClick={() => go(-1)} className="absolute left-4 sm:left-8 w-12 h-12 grid place-items-center rounded-full bg-white/[0.06] border border-white/[0.1] text-white hover:bg-white/[0.14] backdrop-blur-md"><ChevronLeft size={22}/></button>
        <button type="button" aria-label="Следующий кадр" onClick={() => go(1)} className="absolute right-4 sm:right-8 w-12 h-12 grid place-items-center rounded-full bg-white/[0.06] border border-white/[0.1] text-white hover:bg-white/[0.14] backdrop-blur-md"><ChevronRight size={22}/></button>
      </>}
    </div>
    <div className="px-4 sm:px-20 pb-5 flex flex-col items-center gap-4">
      <div className={`flex items-center gap-1 p-1.5 rounded-full border backdrop-blur-xl ${glass(isNoir)}`}>
        <span className="px-3 font-mono text-[11px] tabular-nums text-zinc-300">{String(index + 1).padStart(2, '0')} / {String(count).padStart(2, '0')}</span>
        <button type="button" aria-label={zoom ? 'Уменьшить кадр' : 'Увеличить кадр'} onClick={() => setZoom(z => !z)} className={button}>{zoom ? <ZoomOut size={16}/> : <ZoomIn size={16}/>}</button>
        <button type="button" aria-label="Кадры на весь экран" onClick={() => document.fullscreenElement ? document.exitFullscreen?.() : root.current?.requestFullscreen?.()} className={button}><Maximize2 size={15}/></button>
        <button type="button" aria-label="Закрыть кадры" onClick={() => setIndex(null)} className={button}><X size={16}/></button>
      </div>
      {count > 1 && <div ref={strip} className="w-full max-w-5xl flex gap-2.5 overflow-x-auto pb-1 [scrollbar-width:none]">
        {images.map((url, i) => <button key={url + i} data-i={i} type="button" onClick={() => { setDir(i > index ? 1 : -1); setZoom(false); setIndex(i); }} aria-label={caption + ' ' + (i + 1)} aria-current={i === index ? 'true' : undefined}
          className={`relative shrink-0 w-28 aspect-video rounded-xl overflow-hidden border kt-cover transition-all duration-500 ${i === index ? (isNoir ? 'border-white opacity-100 scale-105' : 'border-rose-400 opacity-100 scale-105 shadow-[0_0_24px_rgba(225,29,72,0.45)]') : 'border-white/10 opacity-45 hover:opacity-90'} ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(url, i)}</button>)}
      </div>}
    </div>
  </motion.div>;
}

export function StillsMosaic({k, isNoir, images, renderArtwork, caption = 'Кадр'}) {
  const [index, setIndex] = useState(null), [ref, entered] = useEntered();
  const limit = typeof matchMedia === 'function' && matchMedia('(min-width: 1280px)').matches ? 12 : 9, tiles = images.slice(0, limit);
  // The last frame stretches over what the final row leaves, so the mosaic has no holes.
  const cols = typeof matchMedia !== 'function' ? 4 : matchMedia('(min-width: 1280px)').matches ? 5 : matchMedia('(min-width: 640px)').matches ? 4 : 2;
  const spare = tiles.length > 1 ? (cols - (4 + tiles.length - 1) % cols) % cols : 0;
  return <SectionFrame>
    <div ref={ref} className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-5 gap-3 auto-rows-[clamp(110px,calc((68vh-24px)/3),230px)]">
      {tiles.map((url, i) => {
        const rest = i === limit - 1 && images.length > limit ? images.length - limit + 1 : 0;
        return <KineticItem key={url + i} weight={0.7 + (i % 3) * 0.32} drift={(i % 3) - 1} {...k} className={i === 0 ? 'col-span-2 row-span-2' : ''} style={i > 0 && i === tiles.length - 1 && spare ? {gridColumn: `span ${spare + 1}`} : undefined}>
          <button type="button" onClick={() => setIndex(i)} aria-label={rest ? 'Все кадры · ' + images.length : 'Открыть ' + caption.toLowerCase() + ' ' + (i + 1)}
            className={`group relative w-full h-full rounded-3xl overflow-hidden border text-left bg-white/[0.03] transition-[opacity,transform,clip-path] duration-1000 ease-[cubic-bezier(.22,1,.36,1)] ${isNoir ? 'border-white/20' : 'border-white/[0.08]'} ${entered ? 'opacity-100' : 'opacity-0'}`}
            style={{clipPath: entered ? 'inset(0 0 0 0 round 24px)' : 'inset(40% 10% 40% 10% round 24px)', transitionDelay: entered ? `${i * 60}ms` : '0ms'}}>
            <span className={`absolute inset-0 kt-cover transition-transform duration-[1.2s] ease-out group-hover:scale-110 ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(url, i)}</span>
            <span className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-60 group-hover:opacity-100 transition-opacity"/>
            <span className="absolute left-4 bottom-3 right-4 text-xs font-medium text-white translate-y-2 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 transition-all duration-500">{caption} {i + 1}</span>
            {rest > 0 && <span className="absolute inset-0 grid place-items-center bg-black/60 backdrop-blur-[2px] text-white text-2xl font-black">+{rest}</span>}
          </button>
        </KineticItem>;
      })}
    </div>
    {createPortal(<div className="mv-tw" style={{display: 'contents'}}><AnimatePresence>{index !== null && <FilmViewer key="viewer" images={images} index={index} setIndex={setIndex} isNoir={isNoir} renderArtwork={renderArtwork} caption={caption}/>}</AnimatePresence></div>, document.body)}
  </SectionFrame>;
}
