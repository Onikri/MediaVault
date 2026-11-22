import {useEffect, useState} from 'react';
import {AnimatePresence, motion} from 'motion/react';
import {ChevronLeft, ChevronRight, ExternalLink} from 'lucide-react';
import {loadWatchOrder} from '../../franchise-seasons.js';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, Switch, glass, useEntered} from './ui.jsx';

/* Порядок просмотра as a route: covers on one line, the line draws itself up
   to this title, its checkpoint pulses; hovering a stop lifts it. */
const FORMATS = {tv: 'Сериал', tv_13: 'Сериал', tv_24: 'Сериал', tv_48: 'Сериал', movie: 'Фильм', ova: 'OVA', ona: 'ONA', special: 'Спецвыпуск', tv_special: 'Спецвыпуск', music: 'Клип', pv: 'Промо', cm: 'Реклама'};
const STATE = {before: 'Раньше', current: 'Вы здесь', next: 'Дальше', announced: 'Анонс'};
const CARD = 240, GAP = 24;

export function RouteSection({k, isNoir, identity, server, cached, onLoaded, onRelated, renderImage}) {
  const [value, setValue] = useState(null), [error, setError] = useState(''), [retry, setRetry] = useState(0), [mode, setMode] = useState('main'), [hover, setHover] = useState(null);
  const [ref, entered] = useEntered(.2);
  useEffect(() => {
    const controller = new AbortController();
    setValue(null); setError('');
    if (cached?.version >= 2 && cached?.items && !retry) { setValue(cached); return () => controller.abort(); }
    if (!identity || !server) return () => controller.abort();
    loadWatchOrder(identity, server, {signal: controller.signal}).then(data => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(data?.items)) throw Error('Каталог не предоставил связи произведений.');
      setValue(data); onLoaded?.(data);
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [identity, server, !!cached, retry]);
  const main = value?.seasons || [], hasMain = main.length > 1;
  const items = mode === 'main' && hasMain ? main : value?.items || [];
  const here = Math.max(0, items.findIndex(i => String(i.id) === String(identity)));
  const now = Date.now();
  const state = (item, idx) => idx === here ? 'current' : idx < here ? 'before' : !item.year || (item.date && Date.parse(item.date) > now) ? 'announced' : 'next';
  const ahead = items.length - here - 1, lit = isNoir ? '#fff' : '#f43f5e';
  // The track opens on "Вы здесь" whenever the list or the mode changes.
  useEffect(() => {
    const box = ref.current;
    if (!box || !items.length) return;
    const frame = requestAnimationFrame(() => { box.scrollLeft = Math.max(0, here * (CARD + GAP) + CARD / 2 - box.clientWidth / 2); });
    return () => cancelAnimationFrame(frame);
  }, [value, mode, items.length, here]);
  const page = d => ref.current?.scrollBy({left: d * ref.current.clientWidth * .8, behavior: 'smooth'});
  const arrow = 'grid place-items-center w-9 h-9 rounded-full bg-white/[0.06] border border-white/[0.1] text-zinc-300 hover:text-white hover:bg-white/[0.12] transition-colors';
  if (!value) return <SectionFrame><p className="text-[13px] text-zinc-400" role="status">{error ? <>{error} <button type="button" className="underline underline-offset-4" onClick={() => setRetry(v => v + 1)}>Повторить</button></> : 'Получаем связи франшизы…'}</p></SectionFrame>;
  if (!items.length) return <SectionFrame><p className="text-[13px] text-zinc-400">Связанные произведения пока не указаны.</p></SectionFrame>;
  return <SectionFrame>
    <KineticItem weight={0.8} {...k}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-500">{mode === 'main' && hasMain ? 'Основная история' : 'Все адаптации по дате выхода'}</p>
          <p className="mt-2 text-3xl font-light text-white tabular-nums"><span className="font-black">{here + 1}</span><span className="text-zinc-500"> из {items.length}</span>
            <span className="ml-3 text-[13px] text-zinc-400 font-normal">{ahead > 0 ? `впереди ${ahead}` : 'это последняя часть'}</span></p>
        </div>
        <span className="flex items-center gap-2">{hasMain && <Switch label="Порядок просмотра" value={mode} onChange={setMode} isNoir={isNoir} options={[['main', 'Основные сезоны'], ['all', 'Все произведения']]}/>}
          <button type="button" aria-label="Листать маршрут назад" onClick={() => page(-1)} className={arrow}><ChevronLeft size={16}/></button><button type="button" aria-label="Листать маршрут вперёд" onClick={() => page(1)} className={arrow}><ChevronRight size={16}/></button></span>
      </div>
    </KineticItem>
    {/* Room above and below the track so the current checkpoint's pulse is never clipped. */}
    <div ref={ref} className="relative -mx-2 px-2 py-6 -my-6 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <AnimatePresence mode="wait" initial={false}>
        <motion.ol key={mode} translate="no" aria-label={mode === 'main' && hasMain ? 'Основная история' : 'Порядок выхода'} className="relative w-max mx-auto flex gap-6" initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} transition={{duration: .25}}>
          {/* The line runs through the centres of the checkpoints (row of 24px, centre at 12px). */}
          {items.length > 1 && <>
            <span aria-hidden="true" className="absolute top-[11px] h-[2px] bg-white/[0.08] rounded-full" style={{left: CARD / 2, right: CARD / 2}}/>
            <span aria-hidden="true" className="absolute top-[11px] h-[2px] rounded-full transition-[width] duration-[1.6s] ease-[cubic-bezier(.22,1,.36,1)]" style={{left: CARD / 2, background: `linear-gradient(90deg, ${lit}33, ${lit})`, width: entered ? here * (CARD + GAP) : 0, boxShadow: `0 0 10px ${lit}`}}/>
          </>}
          {items.map((item, idx) => {
            const s = state(item, idx), current = s === 'current', passed = idx < here, open = hover === idx || current;
            return <li key={item.id} aria-current={current ? 'step' : undefined} className="relative shrink-0" style={{width: CARD}} onMouseEnter={() => setHover(idx)} onMouseLeave={() => setHover(null)}>
              <div className="h-6 flex items-center justify-center mb-5">
                <span className={`relative w-[14px] h-[14px] rounded-full grid place-items-center transition-transform duration-500 ${current ? (isNoir ? 'bg-white' : 'bg-rose-500 shadow-[0_0_0_3px_rgba(244,63,94,0.25)]') : passed ? (isNoir ? 'bg-white/70' : 'bg-rose-500/70') : 'bg-[#12090d] border-2 border-white/25'}`}
                  style={{transitionDelay: entered ? `${Math.min(idx, 10) * 160 + 300}ms` : '0ms', transform: entered ? 'scale(1)' : 'scale(0)'}}>
                  {current && <span className={`absolute -inset-[5px] rounded-full border kt-dot-pulse ${isNoir ? 'border-white/70' : 'border-rose-400/80'}`}/>}
                </span>
              </div>
              <button type="button" disabled={current} onClick={() => onRelated?.({...item, kind: 'anime', relation: 'Порядок просмотра', format: item.kind === 'movie' ? 'Фильм' : 'Аниме'})}
                className={`group w-full text-left transition-all duration-500 ${open ? '-translate-y-1.5' : ''} ${entered ? 'opacity-100' : 'opacity-0 translate-y-8'}`} style={{transitionDelay: entered && hover === null ? `${Math.min(idx, 10) * 120}ms` : '0ms'}}>
                <span className={`block rounded-3xl overflow-hidden border transition-all duration-500 ${current ? (isNoir ? 'border-white/70' : 'border-rose-400/60 shadow-[0_30px_60px_-24px_rgba(225,29,72,0.65)]') : isNoir ? 'border-white/20 group-hover:border-white/50' : 'border-white/[0.08] group-hover:border-white/20'} ${glass(isNoir)}`}>
                  <span className={`relative block aspect-[16/10] overflow-hidden ${s === 'announced' ? 'opacity-60' : ''}`}>
                    {item.cover ? <span className={`absolute inset-0 kt-cover kt-top transition-transform duration-700 group-hover:scale-105 ${isNoir ? 'grayscale' : ''}`}>{renderImage(item)}</span>
                      : <span aria-hidden="true" className="absolute inset-0 grid place-items-center text-7xl font-black tracking-tighter text-white/[0.06]">{String(idx + 1).padStart(2, '0')}</span>}
                    <span className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent"/>
                    <span className={`absolute top-3 right-3 px-2.5 py-1 rounded-full text-[10px] font-semibold uppercase tracking-[0.12em] border shadow-[0_4px_14px_rgba(0,0,0,0.5)] ${current ? (isNoir ? 'bg-white text-black border-white' : 'bg-rose-600 text-white border-rose-300/40') : passed ? 'bg-black/75 text-zinc-200 border-white/15' : 'bg-black/75 text-zinc-300 border-white/10'}`}>{STATE[s]}</span>
                  </span>
                  <span className="block p-4">
                    <span className="block text-[15px] font-bold text-white leading-snug line-clamp-2 min-h-[2.6em]">{item.title || 'Название уточняется'}</span>
                    <span className="mt-2 flex items-center gap-2 text-[12px] text-zinc-400"><span className="font-mono text-[11px] text-zinc-500">{String(idx + 1).padStart(2, '0')}</span><span className="text-white/25">·</span>
                      {item.year && <><span className="font-mono text-zinc-300">{item.year}</span><span className="text-white/25">·</span></>}
                      <span>{FORMATS[item.kind] || item.kind || 'Аниме'}</span>
                    </span>
                    <span className={`block overflow-hidden transition-all duration-500 ${open && item.name && item.name !== item.title ? 'max-h-10 opacity-100 mt-2' : 'max-h-0 opacity-0'}`}><span className={`block truncate text-[11px] ${isNoir ? 'text-white' : 'text-rose-200'}`}>{item.name}</span></span>
                  </span>
                </span>
              </button>
            </li>;
          })}
        </motion.ol>
      </AnimatePresence>
    </div>
    <p className="text-[11px] text-zinc-500">Для разных сюжетных веток единого порядка может не быть. <a className="inline-flex items-center gap-1 hover:text-white" href={'https://shikimori.io/animes/' + identity + '/franchise'} target="_blank" rel="noopener noreferrer">Карта связей<ExternalLink size={11}/></a></p>
  </SectionFrame>;
}
