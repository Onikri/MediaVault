import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {ChevronLeft, ChevronRight, LayoutGrid, Rows2} from 'lucide-react';
import {gsap} from '../../motion-icons/gsap-setup.js';
import {Flip} from 'gsap/Flip';
import {KineticItem} from '../kinetic.jsx';
import {glass} from './ui.jsx';

gsap.registerPlugin(Flip);
const GAP = 12, MAP_GAP = 8, ASPECT = 4 / 3;

// The largest cell (3:4) for which every item fits the stage at once.
function fit(count, width, height) {
  let best = {cols: 1, cell: 0};
  for (let cols = 1; cols <= count; cols++) {
    const rows = Math.ceil(count / cols);
    const cell = Math.min((width - (cols - 1) * MAP_GAP) / cols, (height - (rows - 1) * MAP_GAP) / rows / ASPECT);
    if (cell > best.cell) best = {cols, cell: Math.floor(cell)};
  }
  return best;
}

/* Two rows of cards that scroll sideways; the corner button pulls back into a
   panorama: every card shrinks and flies to the top-left into one map of the
   whole cast that fits the stage. Picking a card on the map zooms back into
   that place and the two rows return around it. */
export default function Panorama({items, idOf, renderCard, renderMini, k, isNoir, mapLabel, rowsLabel = 'Ряды', label}) {
  const [map, setMap] = useState(false), [box, setBox] = useState({cols: 1, cell: 0});
  const stage = useRef(null), row = useRef(null), layer = useRef(null), pending = useRef(null);
  const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  useLayoutEffect(() => {
    if (!map) return;
    const update = () => { const r = stage.current?.getBoundingClientRect(); if (r) setBox(fit(items.length, r.width, r.height)); };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, [map, items.length]);
  const flipTargets = node => node ? [...node.querySelectorAll('[data-flip-id]')] : [];
  const toMap = () => {
    const r = stage.current.getBoundingClientRect();
    setBox(fit(items.length, r.width, r.height));
    pending.current = {state: Flip.getState(flipTargets(row.current))};
    setMap(true);
  };
  const zoomTo = id => {
    pending.current = {state: Flip.getState(flipTargets(layer.current)), id};
    setMap(false);
  };
  useLayoutEffect(() => {
    const p = pending.current;
    if (!p) return;
    pending.current = null;
    if (map) {
      if (reduce) return;
      // Pull back: the cards leave their rows and settle into the map, top-left first.
      Flip.from(p.state, {targets: flipTargets(layer.current), duration: .95, ease: 'expo.inOut', scale: true, stagger: {amount: .28, from: 'start'}});
      gsap.fromTo(layer.current, {scale: 1.08, transformOrigin: '0% 0%'}, {scale: 1, duration: 1.1, ease: 'expo.inOut'});
      return;
    }
    const target = row.current.querySelector(`[data-flip-id="${CSS.escape(String(p.id))}"]`);
    if (target) row.current.scrollLeft = Math.max(0, target.offsetLeft - (row.current.clientWidth - target.offsetWidth) / 2);
    if (reduce) return;
    // Zoom in: the rows grow back around the chosen card.
    const card = target?.getBoundingClientRect(), stageBox = stage.current.getBoundingClientRect();
    const origin = card ? `${card.left - stageBox.left + card.width / 2}px ${card.top - stageBox.top + card.height / 2}px` : '50% 50%';
    Flip.from(p.state, {targets: flipTargets(row.current), duration: .85, ease: 'expo.inOut', scale: true});
    gsap.fromTo(row.current, {scale: .9, transformOrigin: origin}, {scale: 1, duration: .95, ease: 'expo.inOut', clearProps: 'transform'});
  }, [map]);
  useEffect(() => {
    if (!map) return;
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); setMap(false); } };
    addEventListener('keydown', key);
    return () => removeEventListener('keydown', key);
  }, [map]);
  const page = d => row.current?.scrollBy({left: d * row.current.clientWidth * .85, behavior: reduce ? 'auto' : 'smooth'});
  const button = 'grid place-items-center w-9 h-9 rounded-full bg-white/[0.06] border border-white/[0.1] text-zinc-300 hover:text-white hover:bg-white/[0.12] transition-colors disabled:opacity-30';
  return <div className="relative">
    <div ref={stage} className="relative">
      <div ref={row} translate="no" aria-label={label} className={`grid grid-rows-2 grid-flow-col gap-3 overflow-x-auto overflow-y-hidden snap-x snap-mandatory [scrollbar-width:none] [&::-webkit-scrollbar]:hidden auto-cols-[calc((100%-12px)/2)] md:auto-cols-[calc((100%-36px)/4)] xl:auto-cols-[calc((100%-60px)/6)] ${map ? 'invisible' : ''}`}>
        {items.map((item, idx) => <KineticItem key={idOf(item)} weight={0.8 + (idx % 3) * 0.14} drift={(idx % 3) - 1} {...k} enabled={k.enabled && !map}>
          <div data-flip-id={idOf(item)} className="snap-start">{renderCard(item, idx)}</div>
        </KineticItem>)}
      </div>
      {map && <div ref={layer} translate="no" role="list" aria-label={mapLabel} className="absolute left-0 top-0 grid content-start justify-start" style={{gridTemplateColumns: `repeat(${box.cols}, ${box.cell}px)`, gap: MAP_GAP}}>
        {items.map(item => <button key={idOf(item)} type="button" role="listitem" data-flip-id={idOf(item)} onClick={() => zoomTo(idOf(item))} aria-label={'Показать ' + (item.name || '')}
          className={`group relative block rounded-2xl overflow-hidden border text-left transition-[border-color,box-shadow] duration-300 ${isNoir ? 'border-white/20 hover:border-white/70' : 'border-white/[0.08] hover:border-rose-300/50 hover:shadow-[0_16px_36px_-16px_rgba(225,29,72,0.6)]'}`}
          style={{width: box.cell, height: box.cell * ASPECT}}>{renderMini(item)}</button>)}
      </div>}
    </div>
    <div className="mt-4 flex items-center justify-end gap-2">
      {!map && <><button type="button" className={button} aria-label="Листать назад" onClick={() => page(-1)}><ChevronLeft size={16}/></button><button type="button" className={button} aria-label="Листать вперёд" onClick={() => page(1)}><ChevronRight size={16}/></button></>}
      <button type="button" aria-pressed={map} onClick={() => map ? zoomTo(null) : toMap()}
        className={`h-9 pl-3 pr-4 inline-flex items-center gap-2 rounded-full border backdrop-blur-md text-[12px] font-semibold transition-colors ${map ? (isNoir ? 'bg-white text-black border-white' : 'bg-rose-600 text-white border-rose-400/40') : `${glass(isNoir)} text-zinc-200 hover:text-white`}`}>
        {map ? <Rows2 size={15}/> : <LayoutGrid size={15}/>}{map ? rowsLabel : mapLabel}<span className="tabular-nums opacity-60">{items.length}</span>
      </button>
    </div>
  </div>;
}
