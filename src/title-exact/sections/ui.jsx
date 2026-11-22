import {useEffect, useLayoutEffect, useRef, useState} from 'react';

/* Shared pieces of the title sections (second design pass): glass, the
   sliding switch, the entrance trigger and the three-quarter-screen frame. */

export const GLASS = 'bg-gradient-to-b from-white/[0.06] to-white/[0.015] border-white/[0.07] shadow-[inset_0_1px_0_rgba(255,255,255,0.07)]';
export const GLASS_NOIR = 'bg-gradient-to-b from-white/[0.08] to-white/[0.02] border-white/20 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]';
export const glass = isNoir => isNoir ? GLASS_NOIR : GLASS;
export const ease = [.22, 1, .36, 1];
export const roundButton = 'w-10 h-10 grid place-items-center rounded-full bg-white/[0.06] border border-white/[0.1] text-zinc-300 hover:text-white hover:bg-white/[0.12] transition-colors disabled:opacity-30';
export const rowScroll = 'overflow-x-auto snap-x snap-mandatory pb-3 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.14)_transparent]';

export function Switch({value, options, onChange, isNoir, label}) {
  const box = useRef(null), [pill, setPill] = useState(null);
  useLayoutEffect(() => {
    const on = box.current?.querySelector('[aria-pressed="true"]');
    if (on) setPill(old => old && old.x === on.offsetLeft && old.w === on.offsetWidth ? old : {x: on.offsetLeft, w: on.offsetWidth});
  }, [value, options.length]);
  return <div ref={box} className={`relative inline-flex max-w-full overflow-x-auto [scrollbar-width:none] items-center gap-1 p-1 rounded-full border backdrop-blur-md ${glass(isNoir)}`} role="group" aria-label={label}>
    {pill && <span aria-hidden="true" className={`absolute top-1 bottom-1 left-0 rounded-full transition-[transform,width] duration-300 ease-[cubic-bezier(.22,1,.36,1)] ${isNoir ? 'bg-white' : 'bg-gradient-to-b from-rose-500 to-rose-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_6px_18px_-6px_rgba(225,29,72,0.7)]'}`} style={{width: pill.w, transform: `translateX(${pill.x}px)`}}/>}
    {options.map(([key, text]) => <button key={key} type="button" aria-pressed={value === key} onClick={() => onChange(key)}
      className={`relative z-10 shrink-0 px-3 py-1.5 rounded-full text-[11px] whitespace-nowrap transition-colors duration-300 ${value === key ? (isNoir ? 'text-black font-semibold' : 'text-white font-semibold') : 'text-zinc-400 hover:text-white'}`}>{text}</button>)}
  </div>;
}

// Plays a section's entrance the first time it is mostly on screen.
export function useEntered(threshold = .25) {
  const ref = useRef(null), [entered, setEntered] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver !== 'function') { setEntered(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setEntered(true); io.disconnect(); } }, {threshold});
    io.observe(node);
    return () => io.disconnect();
  }, []);
  return [ref, entered];
}

// Each chapter fills about three quarters of the screen so the vertical typography reads against it.
export const SectionFrame = ({children, className = '', ...props}) => <div {...props} className={`min-h-[75vh] flex flex-col justify-center gap-6 ${className}`}>{children}</div>;

export const Note = ({children, action}) => <p className="text-[13px] text-zinc-400" role="status">{children}{action}</p>;
