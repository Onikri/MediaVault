import {useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ArrowUpRight, Bell, Check, CheckCheck, Trash2, X} from 'lucide-react';
import {SiteIcon} from '../../motion-icons/MotionIcon.jsx';
import {notificationStore} from '../../notification-store.js';
import {uiLocale} from '../../i18n/index.js';
import {useThemeMode} from '../theme-mode.js';
import NavPopover, {Tw, iconButton} from './NavPopover.jsx';

// "12 мин назад", as in the design; older ones get a date.
function ago(at, now = Date.now()) {
  const minutes = Math.round((now - at) / 60000);
  const format = new Intl.RelativeTimeFormat(uiLocale(), {numeric: 'auto', style: 'short'});
  if (minutes < 1) return format.format(0, 'second');
  if (minutes < 60) return format.format(-minutes, 'minute');
  if (minutes < 24 * 60) return format.format(-Math.round(minutes / 60), 'hour');
  return new Date(at).toLocaleString(uiLocale(), {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}
const dayStart = offset => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() - offset * 864e5; };
const plural = (n, one, few, many) => n % 10 === 1 && n % 100 !== 11 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many;

/* Notification centre: the same message becomes one card with a counter,
   the feed is split into Сегодня / Вчера / Раньше, and a filter keeps only
   the problems or only what finished. */
export default function NavBell({userId, notice, onOpenTask}) {
  const store = useMemo(() => notificationStore(userId), [userId]);
  const items = useSyncExternalStore(store.subscribe, store.getSnapshot), unread = items.filter(n => !n.read).length;
  const [open, setOpen] = useState(false), [filter, setFilter] = useState('all'), [expanded, setExpanded] = useState(null);
  const trigger = useRef(null), noir = useThemeMode() === 'noir', reduce = useReducedMotion();
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => { if (notice) store.push(notice); }, [notice?.id, store]);
  useEffect(() => setOpen(false), [userId]);
  const groups = useMemo(() => {
    const map = new Map();
    for (const n of items) {
      const key = (n.bad ? '!' : '') + n.message.trim().toLowerCase();
      const g = map.get(key) || {key, message: n.message, bad: n.bad, at: n.at, times: [], ids: [], unread: 0, total: 0, taskId: n.taskId};
      g.times.push(n.at); g.ids.push(n.id); g.total += n.count || 1; if (!n.read) g.unread++;
      if (n.at > g.at) { g.at = n.at; g.taskId = n.taskId || g.taskId; }
      map.set(key, g);
    }
    return [...map.values()].sort((a, b) => b.at - a.at);
  }, [items]);
  const counts = {all: groups.length, bad: groups.filter(g => g.bad).length, done: groups.filter(g => !g.bad).length};
  const shown = groups.filter(g => filter === 'all' || (filter === 'bad' ? g.bad : !g.bad));
  const sections = [['Сегодня', g => g.at >= dayStart(0)], ['Вчера', g => g.at >= dayStart(1) && g.at < dayStart(0)], ['Раньше', g => g.at < dayStart(1)]]
    .map(([title, test]) => [title, shown.filter(test)]).filter(([, list]) => list.length);
  const small = 'grid place-items-center w-8 h-8 rounded-full text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors';
  const accentBg = noir ? 'bg-white text-black' : 'bg-rose-600 text-white';
  const openGroup = g => {
    g.ids.forEach(id => store.read(id));
    if (g.taskId) { setOpen(false); onOpenTask?.(g.taskId); return; }
    setExpanded(v => v === g.key ? null : g.key);
  };
  return <Tw>
    <button ref={trigger} type="button" className={'notification-bell ' + iconButton} title="Уведомления"
      aria-label={unread ? 'Уведомления: ' + unread + ' непрочитанных' : 'Уведомления'} aria-expanded={open} aria-controls="notification-center" onClick={() => setOpen(v => !v)}>
      <SiteIcon name="bell" size={18}/>
      {unread > 0 && <span aria-hidden="true" className={`absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full text-[9px] font-bold leading-4 text-center tabular-nums ${accentBg}`}>{Math.min(unread, 99)}</span>}
    </button>
    <NavPopover open={open} anchor={trigger} onClose={close} id="notification-center" title="Уведомления" width={384} className="!p-0 flex flex-col">
      <header className="sticky top-0 z-10 px-4 pt-4 pb-3 bg-inherit backdrop-blur-2xl border-b border-white/[0.06]">
        <div className="flex items-center justify-between gap-3">
          <h2 className="m-0 flex items-center gap-2 text-[15px] font-bold text-white">Уведомления{unread > 0 && <span className={`h-5 min-w-[20px] px-1.5 rounded-full text-[10px] font-bold leading-5 text-center tabular-nums ${accentBg}`}>{unread}</span>}</h2>
          <div className="flex items-center gap-0.5">
            <button type="button" className={small} aria-label="Отметить все прочитанными" title="Прочитать все" disabled={!unread} onClick={() => store.read()}><CheckCheck size={16}/></button>
            <button type="button" className={small} aria-label="Очистить уведомления" title="Очистить" disabled={!items.length} onClick={store.clear}><Trash2 size={15}/></button>
          </div>
        </div>
        {groups.length > 0 && <div className="mt-3 flex gap-1" role="group" aria-label="Какие уведомления">
          {[['all', 'Все'], ['bad', 'Ошибки'], ['done', 'Готово']].filter(([id]) => id === 'all' || counts[id]).map(([id, label]) => <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}
            className={`h-7 px-3 rounded-full text-[11px] font-semibold transition-colors ${filter === id ? (noir ? 'bg-white text-black' : 'bg-rose-600/25 text-white border border-rose-500/35') : 'text-zinc-400 hover:text-white hover:bg-white/[0.06]'}`}>{label} <span className="tabular-nums opacity-60">{counts[id]}</span></button>)}
        </div>}
      </header>
      <div className="px-2 pb-2">
        {sections.length ? sections.map(([title, list]) => <section key={title} className="pt-2">
          <p className="h-7 px-2 flex items-center text-[10px] uppercase tracking-[0.18em] text-zinc-500">{title}</p>
          {list.map((g, i) => <motion.div key={g.key} initial={reduce ? false : {opacity: 0, y: 6}} animate={{opacity: 1, y: 0}} transition={{duration: .25, delay: Math.min(i, 8) * .03}}>
            <button type="button" onClick={() => openGroup(g)} aria-expanded={g.taskId ? undefined : expanded === g.key}
              className={`notification-item group w-full flex gap-3 px-2.5 py-2.5 rounded-2xl text-left transition-colors hover:bg-white/[0.05] ${g.unread ? 'bg-white/[0.03]' : ''}`}>
              <span className={`mt-0.5 w-7 h-7 shrink-0 grid place-items-center rounded-full ${g.bad ? (noir ? 'bg-white/10 text-white' : 'bg-rose-500/15 text-rose-300') : 'bg-white/[0.06] text-zinc-300'}`}>{g.bad ? <X size={13}/> : g.taskId ? <ArrowUpRight size={13}/> : <Check size={13}/>}</span>
              <span className="flex-1 min-w-0">
                <span className={`block text-[13px] leading-snug ${g.unread ? 'text-white font-semibold' : 'text-zinc-300 font-medium'} ${expanded === g.key ? '' : 'line-clamp-2'}`}>{g.message}</span>
                <span className="mt-1 flex items-center gap-2 text-[10px] text-zinc-500">
                  <time dateTime={new Date(g.at).toISOString()} className="font-mono">{ago(g.at)}</time>
                  {g.total > 1 && <span className="px-1.5 h-4 leading-4 rounded-full bg-white/[0.07] text-zinc-300 font-semibold tabular-nums">×{g.total}</span>}
                </span>
                <AnimatePresence initial={false}>{expanded === g.key && g.times.length > 1 && <motion.span className="block overflow-hidden" initial={{height: 0, opacity: 0}} animate={{height: 'auto', opacity: 1}} exit={{height: 0, opacity: 0}} transition={{duration: reduce ? 0 : .25}}>
                  <span className="mt-2 flex flex-wrap gap-1">{g.times.slice(0, 12).map(t => <span key={t} className="px-2 h-5 leading-5 rounded-full bg-white/[0.05] font-mono text-[10px] text-zinc-400">{ago(t)}</span>)}{g.times.length > 12 && <span className="px-2 h-5 leading-5 text-[10px] text-zinc-500">ещё {g.times.length - 12}</span>}</span>
                </motion.span>}</AnimatePresence>
              </span>
              {g.unread > 0 && <span className={`mt-2 w-1.5 h-1.5 shrink-0 rounded-full ${noir ? 'bg-white' : 'bg-rose-500'}`} aria-label="Не прочитано"/>}
            </button>
          </motion.div>)}
        </section>) : <div className="px-3 py-10 grid justify-items-center gap-2 text-[12px] text-zinc-500"><Bell size={22} className="opacity-60"/>{items.length ? 'Здесь пусто — смени фильтр' : 'Уведомлений пока нет'}</div>}
        {groups.length > 0 && <p className="px-3 pt-2 pb-1 text-[10px] text-zinc-600">{items.length} {plural(items.length, 'событие', 'события', 'событий')} в {groups.length} {plural(groups.length, 'карточке', 'карточках', 'карточках')}</p>}
      </div>
    </NavPopover>
  </Tw>;
}
