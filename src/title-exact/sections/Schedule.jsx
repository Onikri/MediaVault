import {useEffect, useMemo, useRef, useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ChevronLeft, ChevronRight} from 'lucide-react';
import {jikan} from '../../media-metadata.js';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, Switch, ease, glass} from './ui.jsx';

/* Расписание: a month calendar where every release day is stamped with a
   ring (filled once you are past it, pulsing on the episode you are on),
   a side card for the chosen episode, and «Лента», a timeline by month. */

const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const ON_DAYS = ['по понедельникам', 'по вторникам', 'по средам', 'по четвергам', 'по пятницам', 'по субботам', 'по воскресеньям'];
const pad = n => String(n).padStart(2, '0');
const local = value => { const d = new Date(value); return {y: d.getFullYear(), m: d.getMonth(), d: d.getDate(), w: (d.getDay() + 6) % 7, key: d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())}; };
const LIST_LIMIT = 36;

// Episode dates from the public catalogue, page by page within its request budget.
export function useReleaseSchedule(identity, releases, server, enabled) {
  const generation = useRef(0), [episodes, setEpisodes] = useState([]), [busy, setBusy] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => {
    const version = ++generation.current, controller = new AbortController();
    setEpisodes([]); setError('');
    if (!enabled || !/^\d+$/.test(identity || '')) return () => controller.abort();
    setBusy(true);
    (async () => {
      let page = 1;
      do {
        const data = await jikan('anime/' + identity + '/episodes', {server, signal: controller.signal, params: {page}});
        if (controller.signal.aborted || version !== generation.current) return;
        if (!Array.isArray(data.data)) throw Error();
        setEpisodes(old => [...new Map([...old, ...data.data.filter(x => x.aired).map(x => ({episode: x.mal_id, date: x.aired, title: x.title, titleRomanji: x.title_romanji, titleJapanese: x.title_japanese, filler: x.filler, recap: x.recap}))].map(x => [String(x.episode), x])).values()]);
        if (!data.pagination?.has_next_page) break;
        page++;
        await new Promise((resolve, reject) => { const timer = setTimeout(() => { controller.signal.removeEventListener('abort', cancel); resolve(); }, 1100), cancel = () => { clearTimeout(timer); reject(controller.signal.reason); }; controller.signal.addEventListener('abort', cancel, {once: true}); });
      } while (page <= 20);
    })().catch(() => { if (!controller.signal.aborted) setError('Не удалось получить все даты.'); }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [enabled, identity, server, retry]);
  const values = useMemo(() => {
    const merged = new Map();
    for (const item of [...episodes, ...releases]) if (item.date && Number.isFinite(Date.parse(item.date))) merged.set(String(item.episode), {...merged.get(String(item.episode)), ...item});
    return [...merged.values()].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
  }, [episodes, releases]);
  return {values, busy, error, retry: () => setRetry(v => v + 1)};
}

function Stamp({episode, watched, current, isNoir}) {
  const ring = isNoir ? '#fff' : '#f43f5e';
  return <svg viewBox="0 0 64 64" className="absolute inset-0 m-auto w-[78%] h-[78%] overflow-visible" aria-hidden="true">
    {current && <circle cx="32" cy="32" r="30" fill="none" stroke={ring} strokeWidth="1.5" className="kt-pulse" opacity=".6"/>}
    <circle cx="32" cy="32" r="24" fill={watched ? ring : 'none'} fillOpacity={watched ? (current ? 1 : .22) : 0} stroke={ring} strokeWidth="2" strokeDasharray={watched ? 'none' : '3 4'}/>
    <text x="32" y="37" textAnchor="middle" fontWeight="900" fontSize={String(episode).length > 2 ? 12 : 15} fill={current && isNoir ? '#000' : '#fff'}>{episode}</text>
  </svg>;
}

export function ScheduleSection({k, isNoir, identity, releases = [], server, activeEpisode = 0, onEpisode, total}) {
  const root = useRef(null), [enabled, setEnabled] = useState(false), reduce = useReducedMotion();
  useEffect(() => {
    if (typeof IntersectionObserver !== 'function') { setEnabled(true); return; }
    const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { setEnabled(true); observer.disconnect(); } }, {rootMargin: '200px'});
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  const {values, busy, error, retry} = useReleaseSchedule(identity, releases, server, enabled);
  const [view, setView] = useState('calendar'), [month, setMonth] = useState(null), [picked, setPicked] = useState(null), [all, setAll] = useState(false);
  const now = Date.now();
  const aired = values.filter(v => Date.parse(v.date) <= now);
  // The episode you are on; without one, the latest that came out.
  const focus = values.find(v => Number(v.episode) === Number(picked)) || values.find(v => Number(v.episode) === Number(activeEpisode)) || aired.at(-1) || values[0];
  const months = useMemo(() => [...new Map(values.map(v => { const d = local(v.date); return [d.y * 12 + d.m, d]; })).keys()], [values]);
  const shownMonth = month ?? (focus ? local(focus.date).y * 12 + local(focus.date).m : months[0]);
  const byDay = useMemo(() => Object.fromEntries(values.map(v => [local(v.date).key, v])), [values]);
  const weekday = useMemo(() => { const count = Array(7).fill(0); values.forEach(v => count[local(v.date).w]++); const best = count.indexOf(Math.max(...count)); return count[best] >= Math.max(2, values.length * .6) ? best : -1; }, [values]);
  const isWatched = v => activeEpisode > 0 ? Number(v.episode) <= activeEpisode : false;
  const isCurrent = v => Number(v.episode) === Number(activeEpisode);
  const choose = v => { setPicked(v.episode); onEpisode?.(Number(v.episode)); };
  const title = v => v.title || v.titleRomanji || v.titleJapanese || 'Серия ' + v.episode;
  const say = v => { const d = local(v.date); return d.d + ' ' + MONTHS_GEN[d.m] + ' ' + d.y; };
  const finished = values.length && Date.parse(values.at(-1).date) <= now;
  const totalCount = Number(total) || values.length;
  if (!values.length) return <section ref={root} id="titleSchedule"><SectionFrame><p className="text-[13px] text-zinc-400" role="status">{busy ? 'Получаем даты серий…' : error ? <>{error} <button type="button" className="underline underline-offset-4" onClick={retry}>Повторить</button></> : 'Каталоги пока не предоставили даты серий.'}</p></SectionFrame></section>;
  const y = Math.floor(shownMonth / 12), m = shownMonth % 12;
  const first = new Date(y, m, 1), offset = (first.getDay() + 6) % 7, days = new Date(y, m + 1, 0).getDate();
  const cells = [...Array(offset).fill(null), ...Array.from({length: days}, (_, i) => i + 1)];
  const at = months.indexOf(shownMonth);
  const focusIndex = Math.max(0, values.indexOf(focus));
  const start = all ? 0 : Math.max(0, Math.min(focusIndex - 6, values.length - LIST_LIMIT)), listed = all ? values : values.slice(start, start + LIST_LIMIT);
  const groups = listed.reduce((a, v) => { const d = local(v.date), key = d.y * 12 + d.m; (a.get(key) || a.set(key, []).get(key)).push(v); return a; }, new Map());
  return <section ref={root} id="titleSchedule">
    <SectionFrame>
      <KineticItem weight={0.8} {...k}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className={`text-[11px] uppercase tracking-[0.22em] ${isNoir ? 'text-white' : 'text-rose-300'}`}>{weekday >= 0 ? (finished ? 'Выходила ' : 'Выходит ') + ON_DAYS[weekday] : finished ? 'Даты выхода серий' : 'Выходит'}</p>
            <p className="mt-1 text-2xl font-light text-white">{say(values[0]).replace(/ \d{4}$/, '')} — {say(values.at(-1))}</p>
          </div>
          <Switch label="Вид расписания" value={view} onChange={setView} isNoir={isNoir} options={[['calendar', 'Календарь'], ['list', 'Лента']]}/>
        </div>
      </KineticItem>
      <AnimatePresence mode="wait" initial={false}>
        {view === 'calendar' ? <motion.div key="cal" initial={reduce ? false : {opacity: 0, y: 16}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -10}} transition={{duration: .35, ease}}>
          <KineticItem weight={1.05} {...k}>
            <div className="grid lg:grid-cols-[minmax(0,1fr)_260px] gap-6 items-stretch">
              <div className={`p-4 sm:p-6 rounded-3xl border ${glass(isNoir)}`}>
                <div className="flex items-center justify-between mb-5">
                  <button type="button" aria-label="Предыдущий месяц" disabled={at <= 0} onClick={() => setMonth(months[at - 1])} className="w-9 h-9 grid place-items-center rounded-full bg-white/[0.05] hover:bg-white/[0.12] text-zinc-300 disabled:opacity-30"><ChevronLeft size={16}/></button>
                  <AnimatePresence mode="wait" initial={false}><motion.p key={shownMonth} initial={reduce ? false : {opacity: 0, y: 8}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -8}} transition={{duration: .25}} className="text-lg font-black tracking-tight text-white">{MONTHS[m]} <span className="font-mono font-normal text-zinc-500 text-sm">{y}</span></motion.p></AnimatePresence>
                  <button type="button" aria-label="Следующий месяц" disabled={at < 0 || at >= months.length - 1} onClick={() => setMonth(months[at + 1])} className="w-9 h-9 grid place-items-center rounded-full bg-white/[0.05] hover:bg-white/[0.12] text-zinc-300 disabled:opacity-30"><ChevronRight size={16}/></button>
                </div>
                <div className="grid grid-cols-7 gap-1 text-center max-w-[640px] mx-auto">
                  {DAYS.map((d, i) => <span key={d} className={`pb-2 text-[10px] font-mono uppercase tracking-[0.16em] ${i === weekday ? (isNoir ? 'text-white' : 'text-rose-300') : 'text-zinc-500'}`}>{d}</span>)}
                  {cells.map((day, i) => {
                    if (!day) return <span key={'x' + i} className="aspect-square"/>;
                    const v = byDay[y + '-' + pad(m + 1) + '-' + pad(day)];
                    return v ? <button key={day} type="button" onClick={() => choose(v)} title={`Серия ${v.episode} · ${title(v)}`} aria-label={`Серия ${v.episode}, ${say(v)}`} aria-pressed={focus === v}
                      className={`group relative aspect-square rounded-2xl grid place-items-center transition-transform duration-300 hover:scale-110 ${focus === v ? 'bg-white/[0.05]' : ''}`}>
                      <Stamp episode={v.episode} watched={isWatched(v) || (!activeEpisode && Date.parse(v.date) <= now)} current={isCurrent(v)} isNoir={isNoir}/>
                      <span className="absolute top-1 left-1.5 text-[9px] font-mono text-zinc-500">{day}</span>
                      {(v.filler || v.recap) && <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] font-mono uppercase text-amber-300/80">{v.recap ? 'рекап' : 'филлер'}</span>}
                    </button> : <span key={day} className="aspect-square grid place-items-center text-[12px] font-mono text-zinc-600">{day}</span>;
                  })}
                </div>
              </div>
              {focus && <div className={`p-6 rounded-3xl border flex flex-col gap-5 ${glass(isNoir)}`} translate="no">
                <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Серия {focus.episode}{focus.recap ? ' · рекап' : focus.filler ? ' · филлер' : ''}</p>
                <p className="text-2xl font-black tracking-tight text-white leading-tight line-clamp-4">{title(focus)}</p>
                <p className="text-[13px] text-zinc-400">{Date.parse(focus.date) <= now ? 'вышла' : 'выйдет'} {say(focus)}</p>
                {onEpisode && Date.parse(focus.date) <= now && <button type="button" onClick={() => onEpisode(Number(focus.episode))} className={`self-start h-9 px-4 rounded-full text-[12px] font-semibold ${isNoir ? 'bg-white text-black' : 'bg-rose-600 hover:bg-rose-500 text-white'}`}>Смотреть серию</button>}
                <div className="mt-auto">
                  <div className="flex justify-between text-[10px] font-mono text-zinc-500 mb-2"><span>Вышло</span><span>{aired.length} / {totalCount}</span></div>
                  <div className="h-1.5 rounded-full bg-white/10 overflow-hidden"><div className={`h-full rounded-full transition-[width] duration-700 ${isNoir ? 'bg-white' : 'bg-gradient-to-r from-rose-600 to-rose-400'}`} style={{width: Math.min(100, aired.length / Math.max(1, totalCount) * 100) + '%'}}/></div>
                </div>
              </div>}
            </div>
          </KineticItem>
        </motion.div> : <motion.div key="list" initial={reduce ? false : {opacity: 0, y: 16}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -10}} transition={{duration: .35, ease}} className="space-y-10" translate="no">
          {/* «Лента»: a timeline by month; big day numerals, lit up to the episode you are on. */}
          {[...groups].map(([key, list]) => <div key={key} className="grid grid-cols-[72px_minmax(0,1fr)] sm:grid-cols-[88px_minmax(0,1fr)] gap-4 sm:gap-6">
            <p className="pt-3 text-[11px] uppercase tracking-[0.22em] text-zinc-500 self-start">{MONTHS[key % 12]}<span className="block mt-1 font-mono text-[10px] tracking-normal text-zinc-600">{Math.floor(key / 12)}</span></p>
            <ol className="relative border-l border-white/[0.08] pl-6 sm:pl-8 space-y-3">
              {list.map((v, idx) => {
                const watched = isWatched(v), current = isCurrent(v), out = Date.parse(v.date) <= now;
                return <KineticItem key={v.episode} weight={0.8 + (idx % 3) * 0.1} {...k}><li className="relative">
                  <span className={`absolute -left-[31px] sm:-left-[39px] top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 ${current ? (isNoir ? 'bg-white border-white' : 'bg-rose-500 border-rose-300 shadow-[0_0_16px_rgba(244,63,94,0.8)]') : watched ? (isNoir ? 'bg-white/50 border-white/50' : 'bg-rose-500/40 border-rose-400/60') : 'bg-[#12090d] border-white/20'}`}/>
                  <button type="button" onClick={() => choose(v)} className={`group w-full grid grid-cols-[52px_minmax(0,1fr)_auto] sm:grid-cols-[64px_minmax(0,1fr)_auto] items-center gap-4 sm:gap-5 px-4 sm:px-5 py-4 rounded-2xl border text-left transition-all duration-300 hover:translate-x-1 ${current ? (isNoir ? 'bg-white/10 border-white/40' : 'bg-rose-950/40 border-rose-500/35') : glass(isNoir) + ' hover:border-white/20'}`}>
                    <span className={`font-black text-3xl sm:text-4xl leading-none tabular-nums ${out ? 'text-white' : 'text-zinc-600'}`}>{pad(local(v.date).d)}</span>
                    <span className="min-w-0">
                      <span className={`block text-[10px] uppercase tracking-[0.2em] ${isNoir ? 'text-zinc-300' : 'text-rose-300/90'}`}>Серия {v.episode}{v.recap ? ' · рекап' : v.filler ? ' · филлер' : ''}</span>
                      <span className="block mt-1 text-base font-bold text-white truncate">{title(v)}</span>
                    </span>
                    <span className={`text-[11px] font-mono ${current ? (isNoir ? 'text-white' : 'text-rose-200') : watched ? 'text-zinc-400' : 'text-zinc-600'}`}>{current ? 'смотрите' : watched ? 'просмотрено' : out ? 'вышла' : 'ожидается'}</span>
                  </button>
                </li></KineticItem>;
              })}
            </ol>
          </div>)}
          {values.length > LIST_LIMIT && <button type="button" onClick={() => setAll(v => !v)} className={`px-5 py-2.5 rounded-full border backdrop-blur-md text-[12px] font-medium text-zinc-200 hover:text-white ${glass(isNoir)}`}>{all ? 'Свернуть ленту' : 'Все серии · ' + values.length}</button>}
        </motion.div>}
      </AnimatePresence>
      <p className="text-[11px] text-zinc-500">{busy ? 'Получаем даты… ' + values.length + ' · ' : ''}{error ? <button type="button" className="underline underline-offset-4" onClick={retry}>{error} Повторить</button> : null} Оригинальные даты выпуска. График выбранной озвучки может отличаться.</p>
    </SectionFrame>
  </section>;
}
