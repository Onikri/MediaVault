import {Menu, X} from 'lucide-react';
import {MotionIcon, SiteIcon, glyph} from '../../motion-icons/MotionIcon.jsx';
import {useThemeMode} from '../theme-mode.js';
import {NavSearchSlot} from './NavSearch.jsx';
import '../title-exact.css';

/* The navbar of the approved design (motion lab title demo), markup and
   classes as in the reference: a haze over the page, an open bar that drops
   from the edge and condenses into a floating glass capsule as --nav-t goes
   0 → 1 (the title page drives it from its showcase, other pages from the
   scroll). Phones and tablets get the menu button; their sections live in the
   dock. */
const t = 'var(--nav-t, 0)';

// The morph progress lives on the header itself, not on <html>: changing an
// inherited custom property on the root restyles the whole page every frame.
let navProgress = null, headerNode = null;
export function setNavProgress(value) {
  navProgress = value == null ? null : Number(value).toFixed(4);
  if (!headerNode) return;
  if (navProgress == null) headerNode.style.removeProperty('--nav-t'); else headerNode.style.setProperty('--nav-t', navProgress);
}
const registerHeader = node => { headerNode = node; if (node && navProgress != null) node.style.setProperty('--nav-t', navProgress); };

export function NavBrand({onClick}) {
  return <button type="button" onClick={onClick} aria-label="MediaVault — главная" className="kt-brand flex items-center gap-2.5 text-[15px] font-black tracking-tight text-white shrink-0">
    <MotionIcon glyph={glyph('site')} variant="r" size={28}/>
    <span className="hidden min-[380px]:inline">MediaVault</span>
  </button>;
}

export default function NavShell({links, active, onNavigate, onBrand, onSearch, searchActive, search, menuOpen, onMenu, scrolled, children, extra}) {
  const noir = useThemeMode() === 'noir';
  const go = id => { onMenu(false); onNavigate(id); };
  return <div className="mv-tw" style={{display: 'contents'}}><header ref={registerHeader} className={'kt-navbar fixed top-0 inset-x-0 pointer-events-none' + (scrolled ? ' is-scrolled' : '')} style={{zIndex: 100}}>
    {/* Soft haze over the showcase; it melts away as the bar condenses. */}
    <div className="absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-black/75 via-black/30 to-transparent pointer-events-none" style={{opacity: `max(0, calc(1 - ${t} * 1.15))`}}/>
    <div className="max-w-[1520px] mx-auto px-4 sm:px-8" style={{transform: `translate3d(0, calc(4px + 10px * ${t}), 0)`}}>
      <div className="kt-nav-inner pointer-events-auto relative mx-auto flex items-center justify-between gap-4"
        style={{height: `calc(64px - 10px * ${t})`, paddingLeft: `calc(4px + 16px * ${t})`, paddingRight: `calc(4px + 12px * ${t})`, maxWidth: `calc(100% - 24px * ${t})`}}>
        {/* The glass capsule: its own layer, only opacity and scale change. */}
        <div aria-hidden="true" className={`kt-nav-capsule pointer-events-none absolute inset-0 rounded-full overflow-hidden border backdrop-blur-2xl backdrop-saturate-150 ${noir
          ? 'bg-black/70 border-white/[0.1] shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_18px_50px_-12px_rgba(0,0,0,0.9)]'
          : 'bg-[#12080d]/60 border-white/[0.06] shadow-[inset_0_1px_0_rgba(255,255,255,0.06),0_20px_55px_-14px_rgba(0,0,0,0.88)]'}`}
          style={{opacity: t, transform: `scale(calc(1.018 - .018 * ${t}), calc(.9 + .1 * ${t}))`}}>
          <div className="absolute inset-x-10 top-0 h-[1px]" style={{background: noir ? 'linear-gradient(90deg, transparent, rgba(255,255,255,0.28), transparent)' : 'linear-gradient(90deg, transparent, rgba(255,255,255,0.18) 35%, rgba(244,63,94,0.28) 50%, rgba(255,255,255,0.18) 65%, transparent)'}}/>
        </div>
        {/* Left: the animated mark and the sections with their animated icons. */}
        <div className="kt-nav-left relative z-10 flex items-center gap-2 sm:gap-5 min-[1025px]:gap-6 min-w-0">
          <button type="button" className="min-[1025px]:hidden w-9 h-9 shrink-0 grid place-items-center rounded-full bg-gradient-to-b from-white/[0.08] to-white/[0.02] border border-white/[0.07] text-zinc-300 hover:text-white"
            aria-label={menuOpen ? 'Закрыть меню' : 'Открыть меню'} aria-expanded={menuOpen} aria-controls="blossom-mobile-nav" onClick={() => onMenu(!menuOpen)}>{menuOpen ? <X size={17}/> : <Menu size={17}/>}</button>
          <NavBrand onClick={onBrand}/>
          <nav className="kt-nav-links hidden min-[1025px]:flex items-center gap-1 text-xs text-zinc-400" aria-label="Основная навигация">
            {links.filter(v => v.id !== 'profile').map(v => <button type="button" key={v.id} aria-label={v.label} title={v.label} aria-current={active === v.id ? 'page' : undefined} onClick={() => go(v.id)}
              className={`kt-link flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-colors ${active === v.id ? 'bg-white/[0.08] text-white font-medium' : 'hover:text-white hover:bg-white/[0.05]'}`}>
              <SiteIcon name={v.id} variant="c" size={15}/>
              <span className="kt-link-label max-[1279px]:hidden">{v.label}</span>
            </button>)}
          </nav>
        </div>
        {/* Centre: the ruby button that morphs into the search. */}
        <div className="kt-nav-center header-center-search absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10 hidden min-[1025px]:block">
          <NavSearchSlot open={searchActive} onOpen={onSearch}>{search}</NavSearchSlot>
        </div>
        {/* Right: music island, video dock, notifications, profile. */}
        <div className="kt-nav-actions header-actions relative z-10 flex items-center gap-2 shrink-0" onPointerDownCapture={() => onMenu(false)}>{children}</div>
        {extra}
      </div>
      {/* Phones and tablets: the full list of sections under the bar. */}
      <nav id="blossom-mobile-nav" aria-label="Мобильная навигация" inert={!menuOpen}
        className={`min-[1025px]:hidden pointer-events-auto mt-2 overflow-hidden rounded-3xl border backdrop-blur-2xl backdrop-saturate-150 transition-[max-height,opacity,transform] duration-300 ease-[cubic-bezier(.22,1,.36,1)] ${noir ? 'bg-black/85 border-white/[0.14]' : 'bg-[#12080d]/85 border-white/[0.07]'} ${menuOpen ? 'max-h-[420px] opacity-100 translate-y-0' : 'max-h-0 opacity-0 -translate-y-1 border-transparent'}`}>
        <div className="p-2 grid gap-0.5">
          {links.map(v => <button type="button" key={v.id} id={v.id === 'profile' ? 'profileNav' : v.id === 'library' ? 'libraryNav' : v.id === 'collection' ? 'collectionNav' : undefined}
            aria-current={active === v.id ? 'page' : undefined} onClick={() => go(v.id)}
            className={`kt-menu-link w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-left text-[14px] transition-colors ${active === v.id ? 'bg-white/[0.08] text-white font-medium' : 'text-zinc-300 hover:bg-white/[0.05] hover:text-white'}`}>
            <SiteIcon name={v.id} variant="c" size={17}/>{v.label}
          </button>)}
        </div>
      </nav>
    </div>
  </header></div>;
}
