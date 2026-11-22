import {useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore} from 'react';
import {Bell, CheckCheck, Trash2} from 'lucide-react';
import {SiteIcon} from '../../motion-icons/MotionIcon.jsx';
import {notificationStore} from '../../notification-store.js';
import {uiLocale} from '../../i18n/index.js';
import {useThemeMode} from '../theme-mode.js';
import NavPopover, {Tw, iconButton, label} from './NavPopover.jsx';

// "12 мин назад", as in the design; older ones get a date.
function ago(at, now = Date.now()) {
  const minutes = Math.round((now - at) / 60000);
  const format = new Intl.RelativeTimeFormat(uiLocale(), {numeric: 'auto', style: 'short'});
  if (minutes < 1) return format.format(0, 'second');
  if (minutes < 60) return format.format(-minutes, 'minute');
  if (minutes < 24 * 60) return format.format(-Math.round(minutes / 60), 'hour');
  return new Date(at).toLocaleString(uiLocale(), {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

export default function NavBell({userId, notice, onOpenTask}) {
  const store = useMemo(() => notificationStore(userId), [userId]);
  const items = useSyncExternalStore(store.subscribe, store.getSnapshot), unread = items.filter(n => !n.read).length;
  const [open, setOpen] = useState(false), trigger = useRef(null), noir = useThemeMode() === 'noir';
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => { if (notice) store.push(notice); }, [notice?.id, store]);
  useEffect(() => setOpen(false), [userId]);
  const small = 'grid place-items-center w-7 h-7 rounded-full text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors';
  return <Tw>
    <button ref={trigger} type="button" className={'notification-bell ' + iconButton} title="Уведомления"
      aria-label={unread ? 'Уведомления: ' + unread + ' непрочитанных' : 'Уведомления'} aria-expanded={open} aria-controls="notification-center" onClick={() => setOpen(v => !v)}>
      <SiteIcon name="bell" size={16}/>
      {unread > 0 && <span aria-hidden="true" className={`absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full text-[9px] font-bold leading-4 text-center tabular-nums ${noir ? 'bg-white text-black' : 'bg-rose-600 text-white'}`}>{Math.min(unread, 99)}</span>}
    </button>
    <NavPopover open={open} anchor={trigger} onClose={close} id="notification-center" title="Уведомления" width={320}>
      <div className="flex items-center justify-between pr-1">
        <h2 className={label + ' m-0 font-normal'}>Уведомления</h2>
        <div className="flex items-center gap-0.5">
          <button type="button" className={small} aria-label="Отметить все прочитанными" title="Прочитать все" disabled={!unread} onClick={() => store.read()}><CheckCheck size={15}/></button>
          <button type="button" className={small} aria-label="Очистить уведомления" title="Очистить" disabled={!items.length} onClick={store.clear}><Trash2 size={14}/></button>
        </div>
      </div>
      {items.length ? items.map(n => <button key={n.id} type="button" className="notification-item w-full block px-3 py-2.5 rounded-2xl text-left hover:bg-white/[0.05] transition-colors"
        onClick={() => { store.read(n.id); if (n.taskId) { setOpen(false); onOpenTask?.(n.taskId); } }}>
        <p className={`text-[13px] leading-snug ${n.bad ? (noir ? 'text-white' : 'text-rose-300') : n.read ? 'text-zinc-300' : 'text-white'} ${n.read ? 'font-medium' : 'font-semibold'}`}>{n.message}</p>
        {n.count > 1 && <p className="text-[12px] text-zinc-400 mt-0.5">{n.count} события</p>}
        <time dateTime={new Date(n.at).toISOString()} className="block text-[10px] font-mono text-zinc-600 mt-1">{ago(n.at)}</time>
      </button>) : <div className="px-3 py-8 grid justify-items-center gap-2 text-[12px] text-zinc-500"><Bell size={22} className="opacity-60"/>Уведомлений пока нет</div>}
    </NavPopover>
  </Tw>;
}
