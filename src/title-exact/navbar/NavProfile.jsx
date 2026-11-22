import {useCallback, useRef, useState} from 'react';
import {Check, ChevronRight, Cloud, Download, Gauge, History, LogIn, LogOut, Settings, UserPlus, UsersRound} from 'lucide-react';
import {SiteIcon} from '../../motion-icons/MotionIcon.jsx';
import ProfileAvatar from '../../ProfileAvatar.jsx';
import {uiLocale} from '../../i18n/index.js';
import {THEME_MODES, setKinetics, setThemeMode, useKinetics, useThemeMode} from '../theme-mode.js';
import NavPopover, {Tw, iconButton, label, row} from './NavPopover.jsx';

const avatarFill = '[&_.profile-avatar-image]:w-full [&_.profile-avatar-image]:h-full [&_.profile-avatar-image]:grid [&_.profile-avatar-image]:place-items-center [&_img]:w-full [&_img]:h-full [&_img]:object-cover';
const PREVIEW = {
  classic: 'border-rose-500/30 bg-[radial-gradient(circle_at_70%_25%,rgba(225,29,72,0.55),#12090d_70%)]',
  noir: 'bg-black border-white/25 bg-[radial-gradient(rgba(255,255,255,0.3)_1px,transparent_1px)] [background-size:6px_6px]'
};

// The profile popover of the design (Оформление + Кинетика) holding the account.
export default function NavProfile({state, guest, importActive, onNavigate, onDownloads, onGuests, onControl, onLogin, onGuestLogin, onLogout}) {
  const [open, setOpen] = useState(false), trigger = useRef(null);
  const mode = useThemeMode(), kinetics = useKinetics(), noir = mode === 'noir';
  const close = useCallback(() => setOpen(false), []);
  const go = fn => () => { setOpen(false); fn?.(); };
  const user = state.user || (guest ? {sub: 'guest:' + guest.id, given_name: guest.name, name: guest.name, email: ''} : null);
  const name = user?.given_name || user?.name || 'Гость';
  const role = state.admin ? 'Владелец' : guest ? 'Гостевой профиль' : state.user ? 'Зритель' : 'Не выполнен вход';
  const until = guest?.expiresAt ? 'до ' + new Date(guest.expiresAt * 1000).toLocaleDateString(uiLocale(), {day: 'numeric', month: 'long'}) : guest ? 'без срока' : '';
  const items = [
    state.catalog && {id: 'collection', label: 'Моя коллекция', icon: Cloud, run: () => onNavigate('collection')},
    {id: 'history', label: 'История', icon: History, run: () => onNavigate('history')},
    state.admin && {id: 'downloads', label: 'Загрузки', icon: Download, run: onDownloads, live: importActive},
    state.admin && {id: 'control', label: 'Пульт управления', icon: Gauge, run: onControl},
    state.admin && {id: 'guests', label: 'Гости', icon: UsersRound, run: onGuests},
    {id: 'settings', label: 'Настройки', icon: Settings, run: () => onNavigate('profile'), chevron: true}
  ].filter(Boolean);
  const accent = noir ? 'text-white' : 'text-rose-400';
  const rule = <div className="mx-3 my-1.5 h-px bg-white/[0.07]"/>;
  return <Tw>
    <button ref={trigger} id="profileBtn" type="button" className={`${iconButton} overflow-hidden ${avatarFill}`} aria-haspopup="dialog" aria-expanded={open} aria-label="Профиль" onClick={() => setOpen(v => !v)}>
      {user ? <ProfileAvatar user={user} placeholder={<SiteIcon name="profile" size={19}/>}/> : <SiteIcon name="profile" size={19}/>}
    </button>
    <NavPopover open={open} anchor={trigger} onClose={close} title="Профиль" width={300} className="profile-menu">
      <header className="flex items-center gap-3 px-3 pt-2 pb-3">
        {user && <span className={`w-10 h-10 rounded-full overflow-hidden shrink-0 bg-white/[0.06] border border-white/10 text-[15px] font-bold ${avatarFill}`}><ProfileAvatar user={user}/></span>}
        <span className="min-w-0">
          <strong className="block truncate text-[14px] font-semibold text-white">{user ? name : state.restoring ? 'Восстанавливаем вход…' : 'Ты не вошёл'}</strong>
          <small className="block text-[11px] leading-snug text-zinc-400 break-words">{user ? (user.email || role) : state.restoring ? 'Проверяем сохранённую сессию' : 'Войди, чтобы смотреть онлайн и открыть коллекцию'}</small>
        </span>
      </header>
      {(state.user || guest) && <p className="flex flex-wrap gap-1.5 px-3 pb-2">
        <span className={`h-6 px-2.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.12em] leading-6 ${noir ? 'bg-white/15 text-white' : 'bg-rose-600/20 text-rose-200 border border-rose-500/25'}`}>{role}</span>
        {until && <span className="h-6 px-2.5 rounded-full text-[10px] leading-6 bg-white/[0.06] text-zinc-400">{until}</span>}
      </p>}
      {!guest && !state.restoring && (!state.user || !state.driveConnected) && <div className="grid gap-1.5 px-1 pb-2">
        <button type="button" onClick={go(onLogin)} className={`flex items-center justify-center gap-2 h-10 rounded-full text-[13px] font-semibold ${noir ? 'bg-white text-black hover:bg-zinc-200' : 'bg-rose-600 hover:bg-rose-500 text-white shadow-[0_0_20px_rgba(225,29,72,0.35)]'} transition-colors`}><LogIn size={15}/>Войти через Google</button>
        <button type="button" onClick={go(onGuestLogin)} className="flex items-center justify-center gap-2 h-10 rounded-full text-[13px] text-zinc-200 bg-white/[0.06] hover:bg-white/[0.1] transition-colors"><UserPlus size={15}/>Вход по приглашению</button>
      </div>}
      {state.deviceError && <p className="px-3 pb-2 text-[12px] text-rose-300" role="status">{state.deviceError}</p>}
      {rule}
      <div role="group" aria-label="Оформление">
        <p className={label}>Оформление</p>
        {THEME_MODES.map(([id, title, note]) => <button key={id} type="button" aria-pressed={mode === id} onClick={() => setThemeMode(id)} className={row}>
          <span className={`w-9 h-9 rounded-xl shrink-0 border ${PREVIEW[id]}`}/>
          <span className="flex-1 min-w-0">
            <span className="block text-[13px] font-semibold text-white">{title}</span>
            <span className="block text-[11px] text-zinc-400">{note}</span>
          </span>
          {mode === id && <Check size={15} className={id === 'noir' ? 'text-white' : 'text-rose-400'}/>}
        </button>)}
      </div>
      {rule}
      <button type="button" role="switch" aria-checked={kinetics} onClick={() => setKinetics(!kinetics)} className={row + ' justify-between'}>
        <span>
          <span className="block text-[13px] font-semibold text-white">Кинетика</span>
          <span className="block text-[11px] text-zinc-400">Инерция и морф разделов при прокрутке</span>
        </span>
        <span className={`relative w-9 h-5 shrink-0 rounded-full transition-colors ${kinetics ? (noir ? 'bg-white' : 'bg-rose-600') : 'bg-white/15'}`}>
          <span className={`absolute top-0.5 w-4 h-4 rounded-full transition-all ${kinetics ? 'left-[18px]' : 'left-0.5'} ${kinetics && noir ? 'bg-black' : 'bg-white'}`}/>
        </span>
      </button>
      {rule}
      <nav aria-label="Профиль">
        {items.map(item => <button type="button" key={item.id} onClick={go(item.run)} className={row}>
          <item.icon size={16} className="text-zinc-400 shrink-0"/>
          <span className="flex-1">{item.label}</span>
          {item.live && <span className={`text-[10px] font-semibold uppercase tracking-[0.12em] ${accent}`} aria-label="Идут загрузки">идут</span>}
          {item.chevron && <ChevronRight size={15} className="text-zinc-500"/>}
        </button>)}
      </nav>
      {(state.user || guest) && <>{rule}<button type="button" onClick={go(onLogout)} className={row + ' text-zinc-400'}><LogOut size={16} className="shrink-0"/>Выйти</button></>}
    </NavPopover>
  </Tw>;
}
