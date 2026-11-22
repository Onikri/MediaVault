import {useEffect, useMemo, useRef, useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ChevronLeft, ChevronRight} from 'lucide-react';
import {jikan} from '../../media-metadata.js';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, Switch, ease, glass} from './ui.jsx';

/* Расписание: a season calendar of two months at a time with the release
   weekday lit as a column, the chosen episode under it, and «Лента», a
   timeline by month. */

const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
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

const DAY = 864e5;
const plural = (n, one, few, many) => n % 10 === 1 && n % 100 !== 11 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many;
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

const WEEK = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const RUBY = 'linear-gradient(155deg, #fb7185 0%, #e11d48 52%, #9f1239 100%)';
const PEARL = 'linear-gradient(155deg, #ffffff 0%, #d4d4d8 100%)';

/* Календарь сезона: two months side by side, wide enough to read. The release
   weekday runs down each month as a lit column, so the weekly rhythm is the
   first thing you see; every release day is a tile with the episode number.
   Bright tiles are still to watch, dim ones are watched, the episode you are
   on glows, dashed ones are still to come. */
function SeasonCalendar({values, now, focus, onPick, onWatch, activeEpisode, isNoir, reduce, weekday}) {
  const box = useRef(null), [seen, setSeen] = useState(false), [span, setSpan] = useState(2), [start, setStart] = useState(null), [dir, setDir] = useState(1);
  const months = useMemo(() => [...new Set(values.map(v => { const d = local(v.date); return d.y * 12 + d.m; }))], [values]);
  const byDay = useMemo(() => Object.fromEntries(values.map(v => [local(v.date).key, v])), [values]);
  useEffect(() => {
    if (typeof matchMedia !== 'function') return;
    const query = matchMedia('(min-width: 768px)'), update = () => setSpan(query.matches ? 2 : 1);
    update(); query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    const node = box.current;
    if (!node || typeof IntersectionObserver !== 'function') { setSeen(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect(); } }, {threshold: .25});
    io.observe(node);
    return () => io.disconnect();
  }, []);
  const focusMonth = focus ? local(focus.date).y * 12 + local(focus.date).m : months[0];
  const last = Math.max(0, months.length - span);
  const from = Math.min(last, start ?? Math.max(0, Math.min(months.indexOf(focusMonth), last)));
  const shown = months.slice(from, from + span);
  const go = d => { setDir(d); setStart(Math.max(0, Math.min(last, from + d))); };
  const today = local(now).key, accent = isNoir ? '255,255,255' : '244,63,94';
  const arrow = 'grid place-items-center w-9 h-9 rounded-full bg-white/[0.06] text-zinc-300 hover:text-white hover:bg-white/[0.12] transition-colors disabled:opacity-25 disabled:pointer-events-none';
  const swatch = (style, text) => <span className="inline-flex items-center gap-2"><span className="w-4 h-4 rounded-[5px]" style={style}/>{text}</span>;
  let order = 0;
  const upcoming = values.find(v => Date.parse(v.date) > now);
  return <div ref={box}>
    <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-3 text-[12px] text-zinc-400">
      {activeEpisode > 0 && swatch({background: `rgba(${accent},.2)`}, 'Просмотрено')}
      {swatch({background: isNoir ? PEARL : RUBY}, activeEpisode > 0 ? 'Ждёт просмотра' : 'Вышла')}
      {values.some(v => Date.parse(v.date) > now) && swatch({border: `1.5px dashed rgba(${accent},.6)`}, 'Скоро')}
      {values.some(v => v.filler || v.recap) && <span className="inline-flex items-center gap-2"><span className="w-4 h-[3px] rounded-full bg-amber-300"/>Филлер или рекап</span>}
      {months.length > span && <span className="ml-auto flex items-center gap-2">
        <button type="button" className={arrow} aria-label="Предыдущий месяц" disabled={from <= 0} onClick={() => go(-1)}><ChevronLeft size={16}/></button>
        <button type="button" className={arrow} aria-label="Следующий месяц" disabled={from >= last} onClick={() => go(1)}><ChevronRight size={16}/></button>
      </span>}
    </div>
    <AnimatePresence mode="wait" initial={false} custom={dir}>
      <motion.div key={from + ':' + span} initial={reduce ? false : {opacity: 0, x: dir * 48}} animate={{opacity: 1, x: 0}} exit={reduce ? {opacity: 0} : {opacity: 0, x: dir * -48}} transition={{duration: .34, ease}}
        className={`grid gap-x-10 gap-y-8 ${shown.length > 1 ? 'md:grid-cols-2' : 'max-w-[640px]'}`}>
        {shown.map(key => {
          const y = Math.floor(key / 12), m = key % 12, offset = (new Date(y, m, 1).getDay() + 6) % 7, days = new Date(y, m + 1, 0).getDate();
          const cells = [...Array(offset).fill(null), ...Array.from({length: days}, (_, i) => i + 1)];
          const inMonth = values.filter(v => { const d = local(v.date); return d.y === y && d.m === m; }), count = inMonth.length;
          // The release weekday of this month (broadcasts move between seasons).
          const tally = Array(7).fill(0); inMonth.forEach(v => tally[local(v.date).w]++);
          const lit = Math.max(...tally) >= 2 ? tally.indexOf(Math.max(...tally)) : weekday;
          return <div key={key} className="min-w-0">
            <div className="mb-3 flex items-baseline gap-3">
              <p className="text-[24px] font-black tracking-tight text-white">{MONTHS[m]}</p>
              <span className="text-[14px] text-zinc-500 tabular-nums">{y}</span>
              <span className="ml-auto text-[13px] text-zinc-400 tabular-nums">{count} {plural(count, 'серия', 'серии', 'серий')}</span>
            </div>
            <div className="relative grid grid-cols-7 gap-1.5" translate="no">
              {lit >= 0 && <span aria-hidden="true" className="absolute top-0 bottom-0 rounded-2xl pointer-events-none" style={{left: `calc(${lit} * (100% + 6px) / 7 - 3px)`, width: 'calc((100% - 36px) / 7 + 6px)', background: `linear-gradient(to bottom, rgba(${accent},.13), rgba(${accent},.035))`}}/>}
              {WEEK.map((d, i) => <span key={d} className={`relative h-8 grid place-items-center text-[12px] ${i === lit ? (isNoir ? 'text-white font-semibold' : 'text-rose-200 font-semibold') : i > 4 ? 'text-zinc-400' : 'text-zinc-500'}`}>{d}</span>)}
              {cells.map((day, i) => {
                if (!day) return <span key={'x' + i}/>;
                const dayKey = y + '-' + pad(m + 1) + '-' + pad(day), v = byDay[dayKey], isToday = dayKey === today;
                const dayMark = <span className={`absolute left-1.5 top-1.5 min-w-[22px] h-[22px] px-1 grid place-items-center rounded-full text-[11px] tabular-nums ${isToday ? 'bg-white text-black font-bold' : v ? '' : 'text-zinc-600'}`}>{day}</span>;
                if (!v) return <span key={day} className="relative aspect-[6/5] rounded-xl" aria-label={isToday ? 'Сегодня' : undefined}>{dayMark}</span>;
                const out = !v.expected && Date.parse(v.date) <= now, current = Number(v.episode) === Number(activeEpisode), watched = activeEpisode > 0 && Number(v.episode) < activeEpisode, picked = focus === v;
                const idx = order++, ring = picked && !current ? ', 0 0 0 2px #14080b, 0 0 0 4px rgba(255,255,255,.85)' : '';
                const look = current || (out && !watched) ? {background: isNoir ? PEARL : RUBY, color: isNoir ? '#000' : '#fff', boxShadow: (current ? `0 0 0 2px #fff, 0 12px 34px -6px rgba(${accent},.75)` : `0 10px 24px -14px rgba(${accent},.9)`) + ring}
                  : watched ? {background: `rgba(${accent},.16)`, color: isNoir ? '#e4e4e7' : '#fda4af', boxShadow: ring.slice(2) || undefined}
                  : {background: `rgba(${accent},.04)`, border: `1.5px dashed rgba(${v.expected ? '255,255,255,.22' : accent + ',.55'})`, color: v.expected ? '#71717a' : isNoir ? '#e4e4e7' : '#fda4af', boxShadow: ring.slice(2) || undefined};
                return <button key={day} type="button" onClick={() => onPick(v)} onDoubleClick={() => out && onWatch(v)} aria-pressed={picked}
                  aria-label={`Серия ${v.episode}, ${v.expected ? 'ожидается' : out ? 'вышла' : 'выйдет'} ${day} ${MONTHS_GEN[m]}${current ? ', вы здесь' : ''}`}
                  className={`group relative aspect-[6/5] rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-white/80 transition-[transform,opacity,box-shadow] hover:-translate-y-0.5`}
                  style={{...look, opacity: seen || reduce ? 1 : 0, transform: seen || reduce ? undefined : 'scale(.7)', transitionDuration: reduce ? '0ms' : '520ms', transitionDelay: seen && !reduce ? `${idx * 45}ms` : '0ms', transitionTimingFunction: 'cubic-bezier(.22,1.4,.36,1)'}}>
                  {current && !reduce && <span aria-hidden="true" className="absolute -inset-1 rounded-[14px] border-2 kt-dot-pulse" style={{borderColor: `rgba(${accent},.7)`}}/>}
                  <span className={`absolute left-1.5 top-1.5 min-w-[22px] h-[22px] px-1 hidden md:grid place-items-center rounded-full text-[11px] tabular-nums ${isToday ? 'bg-white text-black font-bold' : 'opacity-75'}`}>{day}</span>
                  <span className="absolute inset-0 grid place-items-center md:place-items-end md:pr-2 md:pb-1.5 text-right leading-none"><span>
                    <span className="hidden lg:block text-[10px] font-medium opacity-80 mb-1">серия</span>
                    <span className="block font-black tabular-nums text-[clamp(17px,1.9vw,28px)] tracking-tight">{v.episode}</span>
                  </span></span>
                  {(v.filler || v.recap) && <span className="absolute left-2 right-2 bottom-1 h-[3px] rounded-full bg-amber-300"/>}
                  {v === upcoming && <span aria-hidden="true" className="absolute left-2 right-2 bottom-1 h-[3px] rounded-full bg-white/10 overflow-hidden"><span className="block h-full rounded-full" style={{width: Math.max(4, Math.min(100, 100 - (Date.parse(v.date) - now) / (7 * DAY) * 100)) + '%', background: isNoir ? '#fff' : '#fb7185'}}/></span>}
                  <span role="tooltip" className="pointer-events-none absolute z-20 bottom-[calc(100%+10px)] left-1/2 -translate-x-1/2 w-max max-w-[240px] px-3 py-2 rounded-xl bg-black/90 border border-white/10 text-left opacity-0 translate-y-1 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-200 shadow-[0_14px_30px_-12px_rgba(0,0,0,0.9)]">
                    <span className="block text-[11px] text-zinc-400">Серия {v.episode}{v.recap ? ', рекап' : v.filler ? ', филлер' : ''}{v.expected ? ', ожидается' : ''}</span>
                    <span className="block mt-0.5 text-[12px] font-semibold text-white leading-snug">{v.expected ? 'Название ещё не объявлено' : v.title || v.titleRomanji || 'Серия ' + v.episode}</span>
                  </span>
                </button>;
              })}
            </div>
          </div>;
        })}
      </motion.div>
    </AnimatePresence>
  </div>;
}

export function ScheduleSection({k, isNoir, identity, releases = [], server, activeEpisode = 0, onEpisode, total}) {
  const root = useRef(null), [enabled, setEnabled] = useState(false), reduce = useReducedMotion();
  useEffect(() => {
    if (typeof IntersectionObserver !== 'function') { setEnabled(true); return; }
    const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { setEnabled(true); observer.disconnect(); } }, {rootMargin: '200px'});
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  const {values: known, busy, error, retry} = useReleaseSchedule(identity, releases, server, enabled);
  // Episodes still to come follow the weekly rhythm of the last ones: marked as expected.
  const values = useMemo(() => {
    const count = Number(total) || 0, last = known.at(-1);
    if (!last || count <= known.length || known.length < 2) return known;
    const gap = Date.parse(last.date) - Date.parse(known.at(-2).date);
    if (Math.abs(gap - 7 * 864e5) > 864e5) return known;
    const extra = [];
    for (let n = known.length + 1, i = 1; n <= count; n++, i++) extra.push({episode: Number(last.episode) + i, date: new Date(Date.parse(last.date) + i * 7 * 864e5).toISOString(), expected: true});
    return [...known, ...extra];
  }, [known, total]);
  const [view, setView] = useState('calendar'), [picked, setPicked] = useState(null), [all, setAll] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(t); }, []);
  const aired = values.filter(v => !v.expected && Date.parse(v.date) <= now);
  // The episode you are on; without one, the latest that came out.
  const focus = values.find(v => Number(v.episode) === Number(picked)) || values.find(v => Number(v.episode) === Number(activeEpisode)) || aired.at(-1) || values[0];
  const weekday = useMemo(() => { const count = Array(7).fill(0); values.forEach(v => count[local(v.date).w]++); const best = count.indexOf(Math.max(...count)); return count[best] >= Math.max(2, values.length * .6) ? best : -1; }, [values]);
  const isWatched = v => activeEpisode > 0 ? Number(v.episode) <= activeEpisode : false;
  const isCurrent = v => Number(v.episode) === Number(activeEpisode);
  const choose = v => { setPicked(v.episode); onEpisode?.(Number(v.episode)); };
  const title = v => v.title || v.titleRomanji || v.titleJapanese || 'Серия ' + v.episode;
  const say = v => { const d = local(v.date); return d.d + ' ' + MONTHS_GEN[d.m] + ' ' + d.y; };
  const finished = values.length > 0 && !values.some(v => v.expected) && Date.parse(values.at(-1).date) <= now && aired.length >= (Number(total) || values.length);
  const totalCount = Number(total) || values.length;
  // The next episode still to come and the time left to it.
  const next = values.find(v => Date.parse(v.date) > now);
  if (!values.length) return <section ref={root} id="titleSchedule"><SectionFrame><p className="text-[13px] text-zinc-400" role="status">{busy ? 'Получаем даты серий…' : error ? <>{error} <button type="button" className="underline underline-offset-4" onClick={retry}>Повторить</button></> : 'Каталоги пока не предоставили даты серий.'}</p></SectionFrame></section>;
  const focusIndex = Math.max(0, values.indexOf(focus));
  const start = all ? 0 : Math.max(0, Math.min(focusIndex - 6, values.length - LIST_LIMIT)), listed = all ? values : values.slice(start, start + LIST_LIMIT);
  const groups = listed.reduce((a, v) => { const d = local(v.date), key = d.y * 12 + d.m; (a.get(key) || a.set(key, []).get(key)).push(v); return a; }, new Map());
  const countdown = next ? (() => { const ms = Date.parse(next.date) - now, d = Math.floor(ms / DAY), h = Math.floor(ms / 36e5) % 24, mi = Math.max(1, Math.floor(ms / 6e4) % 60); return d ? `${d} ${plural(d, 'день', 'дня', 'дней')} ${h} ${plural(h, 'час', 'часа', 'часов')}` : h ? `${h} ${plural(h, 'час', 'часа', 'часов')} ${mi} мин` : `${mi} мин`; })() : '';
  const rhythm = weekday >= 0 ? ON_DAYS[weekday] : '';
  const sentence = finished
    ? `Сезон вышел целиком: ${aired.length} ${plural(aired.length, 'серия', 'серии', 'серий')}${rhythm ? ' ' + rhythm : ''}, с ${say(values[0])} по ${say(values.at(-1))}.`
    : `Выходит${rhythm ? ' ' + rhythm : ''}. ${next ? `Серия ${next.episode}${next.expected ? ', по графику,' : ''} через ${countdown}.` : ''} Вышло ${aired.length} из ${totalCount}.`;
  return <section ref={root} id="titleSchedule">
    <SectionFrame className="!min-h-0 py-6">
      <KineticItem weight={0.8} {...k}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="max-w-[78ch] text-[16px] leading-relaxed text-zinc-200">{sentence}</p>
          <Switch label="Вид расписания" value={view} onChange={setView} isNoir={isNoir} options={[['calendar', 'Календарь'], ['list', 'Лента']]}/>
        </div>
      </KineticItem>
      <AnimatePresence mode="wait" initial={false}>
        {view === 'calendar' ? <motion.div key="cal" initial={reduce ? false : {opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} transition={{duration: .25}}>
          <KineticItem weight={1.02} {...k}>
            <SeasonCalendar values={values} now={now} focus={focus} onPick={v => setPicked(v.episode)} onWatch={choose} activeEpisode={activeEpisode} isNoir={isNoir} reduce={reduce} weekday={weekday}/>
            {focus && <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 pt-5 border-t border-white/[0.07]" translate="no">
              <p className="text-[13px] text-zinc-400 tabular-nums">Серия {focus.episode}, {focus.expected ? 'ожидается около' : Date.parse(focus.date) <= now ? 'вышла' : 'выйдет'} {say(focus)}{focus.recap ? ', рекап' : focus.filler ? ', филлер' : ''}</p>
              <AnimatePresence mode="wait" initial={false}><motion.p key={focus.episode} initial={reduce ? false : {opacity: 0, y: 6}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -4}} transition={{duration: .2}} className="flex-1 min-w-[200px] text-[18px] font-bold text-white truncate">{focus.expected ? 'Название ещё не объявлено' : title(focus)}</motion.p></AnimatePresence>
              {onEpisode && !focus.expected && Date.parse(focus.date) <= now && <button type="button" onClick={() => onEpisode(Number(focus.episode))} className={`h-10 px-5 rounded-full text-[13px] font-semibold transition-colors ${isNoir ? 'bg-white text-black hover:bg-zinc-200' : 'bg-rose-600 hover:bg-rose-500 text-white shadow-[0_10px_26px_-8px_rgba(225,29,72,0.65)]'}`}>Смотреть серию {focus.episode}</button>}
            </div>}
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
