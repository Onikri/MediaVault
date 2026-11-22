import {forwardRef, useEffect, useRef, useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {Headphones, Maximize2, Minimize2, Pause, Play, SkipBack, SkipForward} from 'lucide-react';
import {useThemeMode} from '../theme-mode.js';
import {GLASS_PILL, Tw, iconButton} from './NavPopover.jsx';

const PHONE = '(max-width: 640px)';
function usePhone() {
  const [phone, setPhone] = useState(() => typeof matchMedia === 'function' && matchMedia(PHONE).matches);
  useEffect(() => { if (typeof matchMedia !== 'function') return; const m = matchMedia(PHONE), change = () => setPhone(m.matches); change(); m.addEventListener('change', change); return () => m.removeEventListener('change', change); }, []);
  return phone;
}
const clock = value => { const n = Math.max(0, Math.floor(Number(value) || 0)); return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0'); };

/* The design's music island: a spinning cover with a progress ring in the bar;
   it widens into the track, a scrubbable progress line and the transport. The
   full player (lyrics, queue, records, connections) opens from it. */
const NavMusicIsland = forwardRef(function NavMusicIsland({track, title, art, playing, time, duration, canPlay, error, busy,
  onToggle, onSeek, onPrev, onNext, prevDisabled, nextDisabled, panelOpen, onPanel}, ref) {
  const reduce = useReducedMotion(), noir = useThemeMode() === 'noir';
  const [open, setOpen] = useState(false), line = useRef(null), drag = useRef(null);
  const [preview, setPreview] = useState(null);
  const trackId = track?.id, phone = usePhone();
  // A newly started song opens the island, as in the design. Phones have no room
  // in the bar: there the disc opens the full player instead.
  useEffect(() => { setOpen(!!trackId && !phone); }, [trackId, phone]);
  useEffect(() => { const hide = () => setOpen(false); addEventListener('mediavault:search-open', hide); return () => removeEventListener('mediavault:search-open', hide); }, []);
  const progress = duration > 0 ? Math.max(0, Math.min(1, (preview ?? time) / duration)) : 0;
  const at = e => { const r = line.current?.getBoundingClientRect(); return r && duration > 0 ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * duration : null; };
  const down = e => { if (e.button !== 0 || !duration) return; drag.current = e.pointerId; e.currentTarget.setPointerCapture(e.pointerId); setPreview(at(e)); };
  const move = e => { if (drag.current === e.pointerId) setPreview(at(e)); };
  const up = e => { if (drag.current !== e.pointerId) return; drag.current = null; const value = at(e); setPreview(null); if (value != null && e.type !== 'pointercancel') onSeek(value); };
  const key = e => {
    if (!duration) return;
    const step = e.key === 'ArrowRight' ? 5 : e.key === 'ArrowLeft' ? -5 : 0;
    if (step) { e.preventDefault(); onSeek(Math.max(0, Math.min(duration, time + step))); }
  };
  const accentBar = noir ? 'bg-white' : 'bg-rose-500';
  if (!track) return <Tw><span ref={ref} className="kt-music relative flex">
    <button type="button" className={iconButton} aria-label="Музыкальный плеер" aria-expanded={panelOpen} onClick={onPanel}><Headphones size={18}/></button>
  </span></Tw>;
  return <Tw><div ref={ref} className={`kt-music relative flex items-center h-9 rounded-full border transition-[background-color,border-color,box-shadow] duration-300 ${open ? `pl-[5px] pr-1.5 gap-2.5 ${GLASS_PILL}` : 'border-transparent'}`}>
    <button type="button" onClick={() => phone ? onPanel() : setOpen(v => !v)} aria-expanded={phone ? panelOpen : open} aria-label={open ? 'Свернуть плеер' : 'Открыть плеер: ' + title} title={error || undefined}
      className="relative w-7 h-7 rounded-full shrink-0">
      <span className={`absolute inset-0 rounded-full overflow-hidden [&_.music-artwork]:absolute [&_.music-artwork]:inset-0 [&_.music-artwork-vinyl]:absolute [&_.music-artwork-vinyl]:inset-0 [&_.music-artwork-vinyl]:grid [&_.music-artwork-vinyl]:place-items-center [&_img]:w-full [&_img]:h-full [&_img]:object-cover ${noir ? 'grayscale' : ''}`}
        style={{animation: 'ktDisc 6s linear infinite', animationPlayState: playing && !reduce ? 'running' : 'paused'}}>{art}</span>
      <span className="absolute inset-[38%] rounded-full bg-[#12080d] border border-white/20"/>
      {!open && <svg className="absolute -inset-[3px] w-[calc(100%+6px)] h-[calc(100%+6px)] -rotate-90 pointer-events-none" viewBox="0 0 36 36" aria-hidden="true">
        <circle cx="18" cy="18" r="16.5" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="2"/>
        <circle cx="18" cy="18" r="16.5" fill="none" stroke={noir ? '#fff' : '#f43f5e'} strokeWidth="2" strokeLinecap="round" pathLength="100" strokeDasharray={`${(progress * 100).toFixed(1)} 100`}/>
      </svg>}
    </button>
    <AnimatePresence initial={false}>{open && <motion.div key="body" className="flex items-center gap-2.5 overflow-hidden" initial={{opacity: 0, width: 0}} animate={{opacity: 1, width: 'auto'}} exit={{opacity: 0, width: 0}} transition={reduce ? {duration: 0} : {duration: .28, ease: [.22, 1, .36, 1]}}>
      <div className="w-[132px] min-w-0">
        <p translate="no" className="truncate text-[11px] font-semibold text-white leading-tight" title={title}>{error ? 'Ошибка аудио' : busy ? 'Подготавливаем…' : title}</p>
        <div className="flex items-center gap-1.5 mt-1">
          <span ref={line} role="slider" tabIndex={0} aria-label="Позиция музыки" aria-valuemin={0} aria-valuemax={Math.round(duration) || 0} aria-valuenow={Math.round(time)} aria-valuetext={clock(time)}
            onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onKeyDown={key}
            className="group relative flex-1 h-3 flex items-center cursor-pointer outline-none">
            <span className="relative w-full h-[2px] group-hover:h-[3px] transition-[height] rounded-full bg-white/15 overflow-hidden"><span className={`absolute inset-y-0 left-0 ${accentBar}`} style={{width: (progress * 100).toFixed(1) + '%'}}/></span>
          </span>
          <span className="font-mono text-[9px] tabular-nums text-zinc-500">{clock(preview ?? time)}</span>
        </div>
      </div>
      <button type="button" aria-label="Предыдущая песня" disabled={prevDisabled} onClick={onPrev} className="text-zinc-400 hover:text-white disabled:opacity-30"><SkipBack size={14}/></button>
      <button type="button" aria-label={playing ? 'Пауза музыки' : 'Продолжить музыку'} disabled={!canPlay} onClick={onToggle}
        className={`grid place-items-center w-7 h-7 shrink-0 rounded-full disabled:opacity-50 ${noir ? 'bg-white text-black' : 'bg-rose-600 text-white shadow-[0_0_14px_rgba(225,29,72,0.55)]'}`}>
        {playing ? <Pause size={12} fill="currentColor"/> : <Play size={12} fill="currentColor" className="ml-px"/>}
      </button>
      <button type="button" aria-label="Следующая песня" disabled={nextDisabled} onClick={onNext} className="text-zinc-400 hover:text-white disabled:opacity-30"><SkipForward size={14}/></button>
      <button type="button" aria-label={panelOpen ? 'Скрыть подробности музыки' : 'Развернуть музыкальный плеер'} aria-expanded={panelOpen} onClick={onPanel}
        className="grid place-items-center w-6 h-6 shrink-0 rounded-full text-zinc-500 hover:text-white hover:bg-white/10">{panelOpen ? <Minimize2 size={12}/> : <Maximize2 size={12}/>}</button>
    </motion.div>}</AnimatePresence>
  </div></Tw>;
});
export default NavMusicIsland;
