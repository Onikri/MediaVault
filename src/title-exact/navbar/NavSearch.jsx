import {createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence, LayoutGroup, motion, useReducedMotion} from 'motion/react';
import {ArrowUpRight, CornerDownLeft, ImageUp, LoaderCircle, Search, X} from 'lucide-react';
import {SEARCH_KINDS, useGlobalSearch} from '../../use-global-search.js';
import {genreLabels, matchesFilters} from '../../catalog.js';
import {Poster} from '../../ImportParts.jsx';
import {useThemeMode} from '../theme-mode.js';
import {Tw, spring} from './NavPopover.jsx';

/* The design's search: the ruby button in the middle of the bar flies into a
   sheet with chips, «Недавние», category filters and the live catalogue
   results (useGlobalSearch) right beneath it. */

const KEY = 'mediavault_search_recents_v1';
const GENRES = [...new Set(Object.values(genreLabels))].sort((a, b) => a.localeCompare(b, 'ru'));
const YEARS = Array.from({length: new Date().getFullYear() + 2 - 1960}, (_, i) => String(new Date().getFullYear() + 1 - i));
const typeLabel = kind => Object.fromEntries(SEARCH_KINDS)[kind] || 'Сериал';
const same = (a, b) => a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();
const Morph = createContext({morph: true, transition: spring});

function Highlight({text, query}) {
  const at = query ? text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()) : -1;
  return at < 0 ? text : <>{text.slice(0, at)}<mark className="bg-transparent text-inherit underline decoration-rose-400/70 underline-offset-2">{text.slice(at, at + query.length)}</mark>{text.slice(at + query.length)}</>;
}

// The trigger and the sheet share one LayoutGroup, so the button morphs into the bar and back.
export function NavSearchSlot({open, onOpen, children}) {
  const reduce = useReducedMotion(), noir = useThemeMode() === 'noir', slot = useRef(null);
  const [morph, setMorph] = useState(true);
  useLayoutEffect(() => {
    if (!open) return;
    // From the phone dock the bar's button is hidden: the sheet just appears.
    const dock = document.documentElement.dataset.searchFrom === 'dock';
    delete document.documentElement.dataset.searchFrom;
    setMorph(!dock && !!slot.current?.getClientRects().length && !reduce);
  }, [open, reduce]);
  const transition = reduce ? {duration: 0} : spring;
  const context = useMemo(() => ({morph, transition}), [morph, transition]);
  return <LayoutGroup id="nav-search"><Tw>
    <span ref={slot} className="kt-search-slot relative block w-8 h-8">
      {!open && <motion.button layoutId="search-shell" transition={transition} type="button" aria-label="Найти в библиотеке" title="Поиск (Ctrl+K)" onClick={onOpen}
        style={{borderRadius: 999}}
        className={`kt-nav-search absolute inset-0 flex items-center justify-center transition-[background-color] ${noir ? 'bg-white text-black shadow-[0_0_20px_rgba(255,255,255,0.3)]' : 'bg-rose-600 hover:bg-rose-500 text-white shadow-[0_0_20px_rgba(225,29,72,0.5)]'}`}>
        <motion.span layoutId="search-icon" transition={transition} className="grid place-items-center"><Search size={15}/></motion.span>
      </motion.button>}
    </span>
  </Tw>
  <Morph.Provider value={context}>{createPortal(<Tw><AnimatePresence>{open && children}</AnimatePresence></Tw>, document.body)}</Morph.Provider>
  </LayoutGroup>;
}

export function SearchSheet({service, onClose, onChoose, onBrowse}) {
  const {morph, transition} = useContext(Morph), noir = useThemeMode() === 'noir', id = useId();
  const [query, setQuery] = useState(''), [kind, setKind] = useState('all'), [year, setYear] = useState(''), [genre, setGenre] = useState('');
  const [chips, setChips] = useState([]), [composing, setComposing] = useState(false), [active, setActive] = useState(0);
  const [recents, setRecents] = useState(() => { try { const saved = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(saved) ? saved.filter(v => typeof v === 'string').slice(0, 5) : []; } catch { return []; } });
  const input = useRef(null), list = useRef(null);
  const searchText = query.trim() || chips.at(-1) || '';
  const state = useGlobalSearch(searchText, kind, service, composing);
  const items = useMemo(() => (year || genre ? state.items.filter(item => matchesFilters({genres: [], ...item}, {year, genre})) : state.items).slice(0, 24), [state.items, year, genre]);
  const searching = searchText.length >= 2;
  useEffect(() => setActive(0), [searchText, kind, year, genre]);
  const persist = next => { setRecents(next); try { localStorage.setItem(KEY, JSON.stringify(next)); } catch {} };
  const remember = term => { const value = term.trim(); if (value) persist([value, ...recents.filter(v => !same(value, v))].slice(0, 5)); };
  const choose = item => { remember(searchText || item.title); onChoose(item); };
  const browse = () => { if (searchText) remember(searchText); onBrowse(searchText, kind === 'all' && !searchText ? 'anime' : kind, {year, genre}); };
  const addChip = text => { const v = text.trim(); if (!v) return; setChips(old => old.some(c => same(c, v)) ? old : [...old, v]); setQuery(''); remember(v); input.current?.focus(); };
  const close = useCallback(() => onClose(), [onClose]);

  useLayoutEffect(() => {
    dispatchEvent(new Event('mediavault:search-open'));
    const t = setTimeout(() => input.current?.focus({preventScroll: true}), 60);
    return () => { clearTimeout(t); dispatchEvent(new Event('mediavault:search-close')); };
  }, []);
  useEffect(() => {
    const escape = e => {
      if (e.key !== 'Escape' || e.isComposing) return;
      e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
      if (query) setQuery(''); else close();
    };
    document.addEventListener('keydown', escape, true);
    return () => document.removeEventListener('keydown', escape, true);
  }, [query, close]);
  const keys = e => {
    if (composing || e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = Math.max(0, Math.min(items.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)));
      setActive(next); list.current?.children[next]?.scrollIntoView({block: 'nearest'});
    }
    if (e.key === 'Enter') { e.preventDefault(); if (searching && items[active]) choose(items[active]); else if (query.trim()) addChip(query); }
    if (e.key === 'Backspace' && !query && chips.length && e.currentTarget.selectionStart === 0) { e.preventDefault(); setChips(c => c.slice(0, -1)); }
  };
  const shell = `kt-search-bar relative w-full flex items-center gap-2.5 h-[52px] pl-4 pr-2.5 border backdrop-blur-2xl shadow-[0_24px_60px_-20px_rgba(0,0,0,0.9)] ${noir ? 'bg-black/85 border-white/20' : 'bg-[#12080d]/85 border-white/[0.1]'}`;
  const accent = noir ? 'text-white' : 'text-rose-300';
  const select = 'h-[30px] max-w-[132px] pl-3 pr-2 rounded-full bg-white/[0.06] hover:bg-white/[0.1] border-0 outline-none text-[11px] font-semibold text-zinc-300 [color-scheme:dark] cursor-pointer';
  return <motion.div role="dialog" aria-label="Поиск в библиотеке" className="kt-search-sheet fixed inset-0 flex justify-center px-3 sm:px-4 pt-[14px]" style={{zIndex: 1300}} initial={{opacity: 1}} exit={{opacity: 1}}>
    <motion.div className="absolute inset-0 bg-black/45 backdrop-blur-[3px]" onClick={close} initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} transition={{duration: .2}}/>
    <div className="relative w-full max-w-[640px] flex flex-col items-center">
      <motion.div layoutId={morph ? 'search-shell' : undefined} transition={transition} style={{borderRadius: 28}} className={shell}
        initial={morph ? undefined : {opacity: 0, y: -10, scale: .98}} animate={morph ? undefined : {opacity: 1, y: 0, scale: 1}} exit={morph ? undefined : {opacity: 0, y: -8, scale: .98}}
        onPointerDown={e => { if (!e.target.closest('button,input,select')) { e.preventDefault(); input.current?.focus(); } }}>
        <span className="pointer-events-none absolute inset-x-10 top-0 h-px" style={{background: noir ? 'linear-gradient(90deg, transparent, rgba(255,255,255,0.28), transparent)' : 'linear-gradient(90deg, transparent, rgba(255,255,255,0.18) 35%, rgba(244,63,94,0.28) 50%, rgba(255,255,255,0.18) 65%, transparent)'}}/>
        <motion.span layoutId={morph ? 'search-icon' : undefined} transition={transition} className="grid place-items-center text-zinc-400"><Search size={17}/></motion.span>
        {chips.length > 0 && <motion.div className="flex items-center gap-1.5 shrink min-w-0 max-w-[45%] overflow-x-auto [scrollbar-width:none]" initial={{opacity: 0}} animate={{opacity: 1, transition: {delay: .12}}} exit={{opacity: 0, transition: {duration: .08}}}>
          <AnimatePresence initial={false}>{chips.map(t => <motion.span key={t} layout="position" initial={{opacity: 0, scale: .7}} animate={{opacity: 1, scale: 1}} exit={{opacity: 0, scale: .7}} transition={spring}
            className="flex items-center gap-1 h-8 pl-3 pr-1 rounded-full bg-white/[0.08] text-[13px] text-zinc-200 whitespace-nowrap">
            <span className="max-w-[140px] truncate" title={t}>{t}</span>
            <button type="button" aria-label={'Удалить фильтр ' + t} onClick={() => { setChips(v => v.filter(x => x !== t)); input.current?.focus(); }} className="grid place-items-center w-6 h-6 rounded-full text-zinc-400 hover:bg-white/10 hover:text-white"><X size={13}/></button>
          </motion.span>)}</AnimatePresence>
        </motion.div>}
        <motion.input ref={input} value={query} onChange={e => setQuery(e.target.value)} onKeyDown={keys} onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
          role="combobox" aria-expanded="true" aria-controls={id + '-hits'} aria-autocomplete="list" aria-label="Поиск произведения" type="text" autoComplete="off" spellCheck={false} enterKeyHint="search" maxLength={160}
          placeholder="Тайтлы, авторы, песни…" style={{outline: 'none', boxShadow: 'none', border: 0, background: 'transparent', minHeight: 0, height: 32, borderRadius: 0}} className="flex-1 min-w-0 bg-transparent border-0 outline-none p-0 text-[15px] text-white placeholder:text-zinc-500"
          initial={{opacity: 0}} animate={{opacity: 1, transition: {delay: .1}}} exit={{opacity: 0, transition: {duration: .08}}}/>
        {state.loading && <LoaderCircle size={16} className="animate-spin text-zinc-500 shrink-0" aria-label="Поиск выполняется"/>}
        <motion.kbd className="hidden sm:block font-mono text-[10px] px-1.5 py-0.5 rounded-md border border-white/10 text-zinc-500" initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}}>Esc</motion.kbd>
        <motion.button type="button" onClick={close} aria-label="Закрыть поиск" className="grid place-items-center w-8 h-8 shrink-0 rounded-full text-zinc-400 hover:bg-white/10 hover:text-white" initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}}><X size={16}/></motion.button>
      </motion.div>
      <motion.div className={`kt-search-panel relative w-full mt-2 rounded-[28px] border backdrop-blur-2xl overflow-hidden shadow-[0_24px_60px_-24px_rgba(0,0,0,0.9)] ${noir ? 'bg-black/85 border-white/20' : 'bg-[#12080d]/85 border-white/[0.1]'}`}
        initial={{opacity: 0, y: -14, scale: .98}} animate={{opacity: 1, y: 0, scale: 1, transition: {...transition, delay: .06}}} exit={{opacity: 0, y: -10, scale: .98, transition: {duration: .14}}}>
        <div className="p-2">
          {!searching && <div>
            <p className="flex items-center justify-between h-9 px-3 text-[11px] uppercase tracking-[0.18em] text-zinc-500">Недавние
              {recents.length > 0 && <button type="button" onClick={() => persist([])} className="normal-case tracking-normal text-[11px] text-zinc-500 hover:text-white">Очистить</button>}
            </p>
            {recents.length ? recents.map(r => <div key={r} className="group flex items-center rounded-2xl hover:bg-white/[0.06]">
              <button type="button" onClick={() => { setQuery(r); input.current?.focus(); }} className="flex-1 min-w-0 flex items-center gap-3 h-11 px-3 text-left text-sm text-zinc-200"><Search size={14} className="text-zinc-500 shrink-0"/><span className="truncate">{r}</span></button>
              <button type="button" aria-label={'Удалить запрос ' + r} onClick={() => persist(recents.filter(v => v !== r))} className="grid place-items-center w-8 h-8 mr-1.5 rounded-full text-zinc-500 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:bg-white/10 hover:text-white"><X size={13}/></button>
            </div>) : <p className="px-3 pb-3 text-[13px] text-zinc-500">Начни вводить название — поиск по каталогам MediaVault.</p>}
          </div>}
          <div className="flex items-center gap-1 px-1.5 pt-2.5 pb-2 mt-1 border-y border-white/[0.06] overflow-x-auto overflow-y-hidden [scrollbar-width:none]" role="group" aria-label="Где искать">
            {SEARCH_KINDS.map(([k, title]) => <button key={k} type="button" onClick={() => setKind(k)} aria-pressed={kind === k} className={`relative shrink-0 h-[30px] px-3 rounded-full text-[11px] font-semibold whitespace-nowrap ${kind === k ? 'text-white' : 'text-zinc-400 hover:text-zinc-200'}`}>
              {kind === k && <motion.span layoutId="search-filter" transition={spring} className={`absolute inset-0 rounded-full ${noir ? 'bg-white/15' : 'bg-rose-600/25 border border-rose-500/35'}`}/>}
              <span className="relative">{title}</span>
            </button>)}
            <span className="flex-1 min-w-2"/>
            <select aria-label="Год выхода" value={year} onChange={e => setYear(e.target.value)} className={select}><option value="">Любой год</option>{YEARS.map(v => <option key={v} value={v}>{v}</option>)}</select>
            <select aria-label="Жанр" value={genre} onChange={e => setGenre(e.target.value)} className={select}><option value="">Любой жанр</option>{GENRES.map(v => <option key={v} value={v}>{v}</option>)}</select>
          </div>
          {searching && <div ref={list} id={id + '-hits'} role="listbox" aria-label="Результаты поиска" aria-busy={state.loading} className="pt-1.5 max-h-[min(46vh,420px)] overflow-y-auto overscroll-contain [scrollbar-width:thin]">
            {items.map((item, i) => <button key={item.id} type="button" role="option" aria-selected={i === active} onMouseEnter={() => setActive(i)} onClick={() => choose(item)}
              className={`w-full flex items-center gap-3 min-h-[62px] px-2.5 py-1.5 rounded-2xl text-left transition-colors ${i === active ? 'bg-white/[0.065]' : ''}`}>
              <span className="relative w-9 h-[50px] shrink-0 rounded-lg overflow-hidden bg-white/[0.05] [&_img]:absolute [&_img]:inset-0 [&_img]:w-full [&_img]:h-full [&_img]:object-cover"><Poster item={item}/></span>
              <span className="flex-1 min-w-0">
                <strong translate="no" className="block truncate text-[13px] font-semibold text-white"><Highlight text={item.title} query={searchText}/></strong>
                <small className="block truncate text-[11px] text-zinc-400 mt-1">{typeLabel(item.kind)}{[item.year, item.authors?.join(', ') || item.artists?.join(', '), item.format].filter(Boolean).map(v => ' · ' + v)}</small>
              </span>
              {i === active && <CornerDownLeft size={14} className={accent}/>}
            </button>)}
            {!state.loading && !items.length && <p className="px-3 py-4 text-[13px] text-zinc-400" role="status">{state.items.length && (year || genre) ? 'С такими фильтрами ничего нет. Сбрось год или жанр.' : 'Ничего не нашлось. Попробуйте другое название или уберите фильтр.'}</p>}
            {state.loading && <p className="px-3 py-3 text-[12px] text-zinc-500" role="status">Каталоги дополняют результаты…</p>}
          </div>}
          <div className="flex items-center justify-between gap-2 px-1.5 pt-2 mt-1 border-t border-white/[0.06]">
            <button type="button" title="Найти аниме, серию и момент по скриншоту. Можно и перетащить картинку на страницу или вставить Ctrl+V." onClick={() => { dispatchEvent(new Event('mediavault:scene-pick')); close(); }}
              className="flex items-center gap-1.5 h-[30px] px-3 rounded-full text-[11px] font-semibold text-zinc-400 hover:text-white hover:bg-white/[0.06]"><ImageUp size={13}/>Найти по кадру</button>
            {(searching || year || genre) && <button type="button" onClick={browse} className={`flex items-center gap-1 h-[30px] px-3 rounded-full text-[11px] font-semibold hover:bg-white/[0.06] ${accent}`}>{searching ? 'Полный поиск' : 'Открыть в библиотеке'}<ArrowUpRight size={13}/></button>}
          </div>
        </div>
      </motion.div>
    </div>
  </motion.div>;
}
