import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {useThemeMode} from '../theme-mode.js';
import '../title-exact.css';

/* The navbar pieces of the approved design (motion lab title demo): glass
   circles in the bar and glass popovers under them. The popovers live in a
   portal so the bar's own blur never clips or flattens them. */

export const spring = {type: 'spring', stiffness: 420, damping: 36, mass: .9};
export const GLASS_PILL = 'bg-gradient-to-b from-white/[0.08] to-white/[0.02] border border-white/[0.07] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]';
export const iconButton = `relative w-9 h-9 shrink-0 rounded-full ${GLASS_PILL} hover:from-white/[0.14] aria-expanded:from-white/[0.14] aria-expanded:border-white/[0.14] flex items-center justify-center text-zinc-300 hover:text-white aria-expanded:text-white transition-colors`;
export const popoverGlass = noir => noir
  ? 'bg-black/85 border-white/[0.14] shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_24px_60px_-20px_rgba(0,0,0,0.9)]'
  : 'bg-[#12080d]/75 border-white/[0.07] shadow-[inset_0_1px_0_rgba(255,255,255,0.07),0_24px_60px_-20px_rgba(0,0,0,0.9)]';
export const label = 'h-8 px-3 flex items-center text-[10px] uppercase tracking-[0.18em] text-zinc-500';
export const row = 'w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-left text-[13px] text-zinc-200 hover:bg-white/[0.05] hover:text-white transition-colors';
export const Tw = ({children}) => <div className="mv-tw" style={{display: 'contents'}}>{children}</div>;

export default function NavPopover({open, anchor, onClose, id, title, width = 288, className = '', children}) {
  const panel = useRef(null), reduce = useReducedMotion(), noir = useThemeMode() === 'noir';
  const [box, setBox] = useState(null);
  useLayoutEffect(() => {
    if (!open) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const r = anchor.current?.getBoundingClientRect();
      if (!r) return;
      const w = Math.min(width, innerWidth - 24);
      const next = {top: Math.round(Math.min(r.bottom + 12, innerHeight - 120)), right: Math.round(Math.max(12, Math.min(innerWidth - r.right, innerWidth - w - 12))), width: w};
      setBox(old => old && old.top === next.top && old.right === next.right && old.width === next.width ? old : next);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    addEventListener('resize', schedule);
    addEventListener('scroll', schedule, true);
    return () => { cancelAnimationFrame(frame); removeEventListener('resize', schedule); removeEventListener('scroll', schedule, true); };
  }, [open, width, anchor]);
  useEffect(() => {
    if (!open) return;
    const away = e => { if (!panel.current?.contains(e.target) && !anchor.current?.contains(e.target)) onClose(); };
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); onClose(); anchor.current?.focus({preventScroll: true}); } };
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('keydown', key); };
  }, [open, onClose, anchor]);
  return createPortal(<Tw><AnimatePresence>{open && box && <motion.section ref={panel} id={id} role="dialog" aria-label={title}
    style={{position: 'fixed', top: box.top, right: box.right, width: box.width, maxHeight: Math.max(160, innerHeight - box.top - 12), zIndex: 1200}}
    initial={reduce ? false : {opacity: 0, y: -8, scale: .97}} animate={{opacity: 1, y: 0, scale: 1}} exit={reduce ? {opacity: 0} : {opacity: 0, y: -6, scale: .98}}
    transition={{duration: reduce ? 0 : .18, ease: [.22, 1, .36, 1]}}
    className={`origin-top-right overflow-y-auto overscroll-contain [scrollbar-width:thin] rounded-3xl border p-2 backdrop-blur-2xl backdrop-saturate-150 text-white ${popoverGlass(noir)} ${className}`}>
    {children}
  </motion.section>}</AnimatePresence></Tw>, document.body);
}
