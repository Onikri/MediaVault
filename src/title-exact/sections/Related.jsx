import {useMemo, useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ArrowUpRight} from 'lucide-react';
import {SectionFrame, Switch, ease, rowScroll} from './ui.jsx';

/* Связи: a filter by kind and one row of large covers. No layout projection
   here (the kinetic section transforms would skew it): the row is re-keyed per filter. */
const TONES = {'Манга': '#fbbf24', 'Ранобэ': '#a78bfa', 'Аниме': '#fb7185', 'Фильм': '#38bdf8', 'OVA': '#34d399', 'ONA': '#2dd4bf', 'Спецвыпуск': '#f472b6'};
const tone = kind => TONES[kind] || '#e4e4e7';
const kindOf = w => w.format || w.kindLabel || (w.kind === 'manga' ? 'Манга' : w.kind === 'ranobe' ? 'Ранобэ' : 'Аниме');
export function RelatedRow({isNoir, related, onOpen, renderImage}) {
  const reduce = useReducedMotion();
  const kinds = useMemo(() => ['Все', ...new Set(related.map(kindOf))], [related]), [kind, setKind] = useState('Все');
  const shown = related.filter(r => kind === 'Все' || kindOf(r) === kind);
  return <SectionFrame>
    {kinds.length > 2 && <div><Switch label="Тип связей" value={kind} onChange={setKind} isNoir={isNoir} options={kinds.map(x => [x, x])}/></div>}
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={kind} translate="no" className={`grid grid-flow-col auto-cols-[46%] md:auto-cols-[calc((100%-40px)/3)] lg:auto-cols-[calc((100%-60px)/4.2)] gap-5 ${rowScroll}`} exit={{opacity: 0, y: -10, transition: {duration: reduce ? 0 : .2}}}>
        {shown.map((w, idx) => <motion.div key={w.kind + w.id} className="snap-start" initial={reduce ? false : {opacity: 0, scale: .92, y: 24}} animate={{opacity: 1, scale: 1, y: 0}} transition={{duration: .5, ease, delay: Math.min(idx, 8) * .06}}>
          <button type="button" onClick={() => onOpen(w)} className="group block w-full text-left">
            <span className={`relative block aspect-[2/3] rounded-3xl overflow-hidden border bg-white/[0.03] transition-all duration-500 group-hover:-translate-y-2 ${isNoir ? 'border-white/20 group-hover:border-white/60' : 'border-white/[0.08] group-hover:border-rose-300/40 group-hover:shadow-[0_28px_60px_-24px_rgba(225,29,72,0.55)]'}`}>
              <span className={`absolute inset-0 kt-cover transition-transform duration-700 group-hover:scale-105 ${isNoir ? 'grayscale' : ''}`}>{renderImage(w)}</span>
              <span className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent"/>
              <span className="absolute top-3 left-3 inline-flex items-center gap-1.5 h-6 px-2.5 rounded-full bg-black/70 border border-white/15 text-[10px] font-semibold text-white shadow-[0_4px_14px_rgba(0,0,0,0.45)]"><span className="w-1.5 h-1.5 rounded-full" style={{background: isNoir ? '#fff' : tone(kindOf(w))}}/>{kindOf(w)}</span>
              <span className="absolute right-3 bottom-3 w-9 h-9 grid place-items-center rounded-full bg-black/40 border border-white/15 text-white opacity-0 translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-500"><ArrowUpRight size={16}/></span>
            </span>
            {w.relation && <span className="block mt-3 text-[10px] uppercase tracking-[0.18em] text-zinc-500">{w.relation}</span>}
            <span className="block mt-1 text-[15px] font-bold text-white leading-snug line-clamp-2">{w.title}</span>
            {w.year && <span className="block mt-1 text-[12px] text-zinc-400">{w.year}</span>}
          </button>
        </motion.div>)}
      </motion.div>
    </AnimatePresence>
  </SectionFrame>;
}
