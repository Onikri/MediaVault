import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ArrowUpRight, BookOpen, ChevronLeft, ChevronRight, ExternalLink, Images, Tv, X} from 'lucide-react';
import {gsap} from '../../motion-icons/gsap-setup.js';
import {SplitText} from 'gsap/SplitText';
import {browseHref} from '../../anime-navigation.js';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, ease, glass, roundButton, rowScroll, useEntered} from './ui.jsx';

gsap.registerPlugin(SplitText);
const ROLES = {main: 'Главный', supporting: 'Второстепенный', background: 'Эпизодический'};
const roleName = role => ROLES[String(role || '').toLowerCase()] || role || '';

/* Персонажи: tall portrait cards in one snapping row; a card flies out into
   the glass dossier (the design's «Досье»). */
export function CharactersRow({k, isNoir, characters, onOpen, renderImage, emptyNote}) {
  const [ref, entered] = useEntered();
  if (!characters?.length) return <SectionFrame><p className="text-[13px] text-zinc-400">{emptyNote}</p></SectionFrame>;
  return <SectionFrame>
    <p className="text-[13px] text-zinc-400">{characters.length} {characters.length % 10 === 1 && characters.length % 100 !== 11 ? 'персонаж' : [2, 3, 4].includes(characters.length % 10) && ![12, 13, 14].includes(characters.length % 100) ? 'персонажа' : 'персонажей'} · нажми на карточку, чтобы открыть досье</p>
    <div ref={ref} translate="no" className={`grid grid-flow-col auto-cols-[calc((100%-16px)/2)] lg:auto-cols-[calc((100%-48px)/4)] gap-4 -mb-3 ${rowScroll}`}>
      {characters.map((c, idx) => <KineticItem key={c.id || c.name} weight={0.8 + (idx % 3) * 0.14} drift={(idx % 3) - 1} {...k}>
        <button type="button" onClick={e => onOpen(c, e.currentTarget)} aria-label={'Досье: ' + c.name}
          className={`kt-char group relative block w-full aspect-[3/5] snap-start rounded-3xl overflow-hidden border text-left transition-[transform,box-shadow,border-color,opacity] duration-700 hover:-translate-y-2 ${isNoir ? 'border-white/20 hover:border-white/60' : 'border-white/[0.08] hover:border-rose-300/40 hover:shadow-[0_28px_60px_-24px_rgba(225,29,72,0.55)]'} ${entered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-10'}`}
          style={{transitionDelay: entered ? `${Math.min(idx, 8) * 70}ms` : '0ms'}}>
          <span className={`absolute inset-0 kt-cover transition-transform duration-700 ease-out group-hover:scale-[1.07] ${isNoir ? 'grayscale' : ''}`}>{renderImage(c)}</span>
          <span className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/25 to-black/10"/>
          <span className="absolute inset-0 rounded-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] pointer-events-none"/>
          {roleName(c.role) && <span className="absolute top-4 left-4 px-2.5 py-1 rounded-full bg-black/30 backdrop-blur-md border border-white/15 text-[10px] uppercase tracking-[0.16em] text-white/90">{roleName(c.role)}</span>}
          <span className="absolute inset-x-5 bottom-5">
            <span className="block text-lg sm:text-xl font-black tracking-tight text-white leading-tight">{c.name}</span>
            {c.voice && <span className={`block mt-1.5 text-[11px] ${isNoir ? 'text-zinc-300' : 'text-rose-200/80'}`}>Сэйю · {c.voice}</span>}
            <span className="mt-3 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-white/0 group-hover:text-white/80 transition-colors duration-500">Досье <ArrowUpRight size={12}/></span>
          </span>
        </button>
      </KineticItem>)}
    </div>
  </SectionFrame>;
}

// Thin bars, the current one long. Changing pages, the coloured drop stretches
// across to the next bar, then its tail pulls in while the bars resize under it.
const BAR = 12, LONG = 32, GAP = 6;
const barLeft = (i, active) => i * (BAR + GAP) + (i > active ? LONG - BAR : 0);
function LiquidPager({index, names, onPick, isNoir}) {
  const drop = useRef(null), last = useRef(index), count = names.length;
  useLayoutEffect(() => {
    const from = last.current, to = index, el = drop.current;
    last.current = index;
    const a = barLeft(from, from), b = barLeft(to, to);
    if (from === to) { gsap.set(el, {left: b, width: LONG}); return; }
    const right = to > from;
    const tl = gsap.timeline()
      .to(el, {left: right ? a : b, width: right ? b + LONG - a : a + LONG - b, duration: .3, ease: 'power2.inOut'})
      .to(el, {left: b, width: LONG, duration: .45, ease: 'back.out(2.2)'});
    return () => tl.kill();
  }, [index]);
  return <div className="relative h-1.5" style={{width: (count - 1) * (BAR + GAP) + LONG}}>
    {names.map((name, i) => <button key={i} type="button" aria-label={name} aria-current={i === index ? 'true' : undefined} onClick={() => onPick(i)}
      className="absolute top-0 h-1.5 rounded-full bg-white/20 hover:bg-white/40 transition-[left,width,background-color] duration-500 ease-[cubic-bezier(.22,1,.36,1)]"
      style={{left: barLeft(i, index), width: i === index ? LONG : BAR}}/>)}
    <span ref={drop} className={`absolute top-0 h-1.5 rounded-full pointer-events-none ${isNoir ? 'bg-white' : 'bg-rose-500'}`}/>
  </div>;
}

/* The dossier: the portrait flies in from the card, the name splits into
   letters. Walking the cast is direction-aware: the text leaves against the
   move and the next one enters with it; the portrait slides the same way. */
export function Dossier({characters, character, busy, error, origin, isNoir, onPick, onClose, renderArtwork, onRelated, workTitle = ''}) {
  const root = useRef(null), art = useRef(null), body = useRef(null), dir = useRef(1), moving = useRef(false), shownIndex = useRef(-1), reduce = useReducedMotion();
  const [spoilers, setSpoilers] = useState(false);
  const found = characters.findIndex(c => String(c.id) === String(character.id));
  const index = found < 0 ? 0 : found, count = characters.length;
  const indexRef = useRef(index); indexRef.current = index;
  useEffect(() => setSpoilers(false), [character.id]);
  useLayoutEffect(() => {
    if (reduce) return;
    const from = origin?.isConnected ? origin.getBoundingClientRect() : null, to = art.current.getBoundingClientRect();
    const tl = gsap.timeline();
    tl.from(root.current.querySelector('.kt-dossier-veil'), {opacity: 0, duration: .4});
    if (from && to.width) tl.from(art.current, {x: from.left - to.left, y: from.top - to.top, scaleX: from.width / to.width, scaleY: from.height / to.height, transformOrigin: '0 0', borderRadius: 24, duration: .75, ease: 'expo.out'}, 0);
    tl.from(root.current.querySelector('.kt-dossier-card'), {opacity: 0, duration: .35}, 0);
    tl.from(root.current.querySelector('.kt-dossier-panel'), {opacity: 0, x: 40, duration: .6, ease: 'expo.out'}, .15);
    return () => tl.kill();
  }, []);
  // The new text enters along the direction of travel; the first open rises from below.
  useLayoutEffect(() => {
    if (shownIndex.current === index) return;
    const first = shownIndex.current < 0;
    shownIndex.current = index;
    if (reduce) { moving.current = false; return; }
    const d = dir.current, name = body.current.querySelector('.kt-dossier-name');
    const split = SplitText.create(name, {type: 'chars', mask: 'chars'}), lines = body.current.querySelectorAll('.kt-dossier-in');
    const tl = gsap.timeline({onComplete: () => { moving.current = false; }});
    if (first) {
      tl.from(split.chars, {yPercent: 110, duration: .6, stagger: .025, ease: 'power4.out'}, .1)
        .from(lines, {opacity: 0, y: 14, stagger: .06, duration: .5, ease: 'power3.out'}, .2);
    } else {
      tl.fromTo(split.chars, {xPercent: d * 120, opacity: 0, skewX: -d * 14}, {xPercent: 0, opacity: 1, skewX: 0, duration: .55, stagger: {each: .022, from: d > 0 ? 'start' : 'end'}, ease: 'power4.out'})
        .fromTo(lines, {x: d * 46, opacity: 0, filter: 'blur(6px)'}, {x: 0, opacity: 1, filter: 'blur(0px)', duration: .5, stagger: .05, ease: 'power3.out'}, .05);
    }
    return () => { tl.kill(); split.revert(); };
  }, [index]);
  // Leave against the move, then load the next character.
  const go = target => {
    const current = indexRef.current, next = (target + count) % count;
    if (moving.current || next === current || count < 2) return;
    moving.current = true;
    const d = target > current ? 1 : -1;
    dir.current = d;
    if (reduce) { onPick(characters[next]); return; }
    const nodes = body.current.querySelectorAll('.kt-dossier-name, .kt-dossier-in');
    gsap.to(nodes, {x: -d * 40, opacity: 0, filter: 'blur(4px)', duration: .22, stagger: .02, ease: 'power2.in',
      onComplete: () => { gsap.set(nodes, {clearProps: 'x,opacity,filter'}); onPick(characters[next]); }});
  };
  const goRef = useRef(go); goRef.current = go;
  useEffect(() => {
    const key = e => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
      if (e.key === 'ArrowRight') goRef.current(indexRef.current + 1);
      if (e.key === 'ArrowLeft') goRef.current(indexRef.current - 1);
    };
    addEventListener('keydown', key);
    root.current?.querySelector('.kt-dossier-close')?.focus({preventScroll: true});
    return () => removeEventListener('keydown', key);
  }, []);
  function openArts() {
    const query = [character.original, ...(character.aliases || []), character.name].find(name => /^[ -~]+$/.test(String(name || '').trim()) && /[a-z]/i.test(name)) || character.original || character.name;
    onClose();
    dispatchEvent(new CustomEvent('mediavault:arts', {detail: {query, title: workTitle}}));
  }
  const accent = isNoir ? 'text-white' : 'text-rose-300';
  const attributes = character.attributes || [], facts = attributes.filter(f => !f.spoiler), spoilerFacts = attributes.filter(f => f.spoiler);
  const voices = character.actors?.length ? character.actors.slice(0, 4).join(', ') : character.voice || character.voiceActors?.map(v => v.name).join(', ');
  const role = roleName(character.role);
  const label = 'text-zinc-500 uppercase tracking-[0.16em] text-[10px]';
  return createPortal(<div className="mv-tw" style={{display: 'contents'}}><div ref={root} className="fixed inset-0 flex items-center justify-center p-3 sm:p-10" style={{zIndex: 1250}} role="dialog" aria-modal="true" aria-label={'Досье: ' + character.name}>
    <div className="kt-dossier-veil absolute inset-0 bg-black/70 backdrop-blur-xl" onClick={onClose}/>
    <div className={`kt-dossier-card relative w-full max-w-6xl max-h-full grid grid-cols-1 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] rounded-[32px] overflow-hidden border ${isNoir ? 'bg-black border-white/20' : 'bg-[#12080d]/90 border-white/[0.08]'} shadow-[0_40px_120px_-20px_rgba(0,0,0,0.9)]`}>
      <div ref={art} className={`relative h-[38vh] md:h-auto md:min-h-[620px] overflow-hidden bg-white/[0.03] ${isNoir ? 'grayscale' : ''}`}>
        <AnimatePresence mode="popLayout" initial={false} custom={dir.current}>
          <motion.span key={character.id} custom={dir.current} className="absolute inset-0 kt-cover kt-top"
            variants={{enter: d => ({opacity: 0, x: d * 90, scale: 1.08}), center: {opacity: 1, x: 0, scale: 1}, exit: d => ({opacity: 0, x: -d * 90, scale: 1.02})}}
            initial={reduce ? false : 'enter'} animate="center" exit="exit" transition={{duration: reduce ? 0 : .65, ease}}>{renderArtwork(character)}</motion.span>
        </AnimatePresence>
        <span className={`absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent md:bg-gradient-to-r md:from-transparent md:via-transparent ${isNoir ? 'md:to-black/90' : 'md:to-[#12080d]/90'}`}/>
        <span className="absolute left-6 bottom-6 font-mono text-[11px] tracking-[0.3em] text-white/60">{String(index + 1).padStart(2, '0')} / {String(count).padStart(2, '0')}</span>
      </div>
      <div ref={body} translate="no" className="kt-dossier-panel relative p-7 sm:p-10 flex flex-col gap-6 overflow-y-auto overscroll-contain max-h-[calc(100vh-24px-38vh)] md:max-h-[calc(100vh-80px)] [scrollbar-width:thin]">
        <button type="button" onClick={onClose} aria-label="Закрыть персонажа" className={`kt-dossier-close absolute top-5 right-5 ${roundButton}`}><X size={18}/></button>
        <p className={`kt-dossier-in pr-12 text-[11px] uppercase tracking-[0.24em] ${accent}`}>{[role, character.nativeName].filter(Boolean).join(' · ') || 'Персонаж'}</p>
        <h3 key={character.id + ':' + character.name} className="kt-dossier-name pr-12 text-4xl sm:text-6xl font-black tracking-tight leading-[0.95] text-white">{character.name}</h3>
        {(character.aliases?.length > 0 || facts.length > 0) && <div className="kt-dossier-in flex flex-wrap gap-2">
          {character.aliases?.slice(0, 3).map(a => <span key={'a' + a} className="px-3 py-1 rounded-full text-[11px] border border-white/15 text-zinc-300">{a}</span>)}
          {facts.slice(0, 6).map(f => <span key={f.key} title={f.source} className={`px-3 py-1 rounded-full text-[11px] border ${isNoir ? 'border-white/25 text-white' : 'border-rose-400/25 bg-rose-500/10 text-rose-200'}`}>{f.label} · {f.value}</span>)}
        </div>}
        <p className="kt-dossier-in text-[15px] leading-[1.75] text-zinc-300 max-w-xl whitespace-pre-line" role={busy ? 'status' : undefined}>{busy && !character.description ? 'Загружаем сведения о персонаже…' : character.description || 'Описание пока не опубликовано в каталоге.'}</p>
        <div className="kt-dossier-in grid grid-cols-2 gap-4 pt-5 border-t border-white/[0.08] text-[12px]">
          <div><p className={label}>Сэйю</p><p className="mt-1.5 text-white font-semibold">{voices || 'Не указаны'}</p></div>
          <div><p className={label}>Арты</p><button type="button" onClick={openArts} className={`mt-1.5 inline-flex items-center gap-1.5 font-semibold ${accent} hover:text-white`}><Images size={14}/>Посмотреть арты</button></div>
        </div>
        {spoilerFacts.length > 0 && <div className="kt-dossier-in">
          <button type="button" aria-expanded={spoilers} onClick={() => setSpoilers(v => !v)} className="text-[12px] text-zinc-400 hover:text-white underline underline-offset-4 decoration-white/20">{spoilers ? 'Скрыть' : 'Показать'} сведения с возможными спойлерами · {spoilerFacts.length}</button>
          {spoilers && <dl className="mt-3 grid gap-2">{spoilerFacts.map(f => <div key={f.key} className="text-[12px]"><dt className={label}>{f.label}</dt><dd className="mt-1 text-zinc-200">{f.value} <a href={f.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-zinc-500 hover:text-white">{f.source}<ExternalLink size={10}/></a></dd></div>)}</dl>}
        </div>}
        {character.appearances?.length > 0 && <div className="kt-dossier-in">
          <p className={label}>Появления в произведениях</p>
          <ul className="mt-2 grid gap-1">{character.appearances.slice(0, 12).map(work => <li key={work.kind + work.id}>
            <button type="button" onClick={() => { onClose(); onRelated?.({...work, ids: {mal: work.id}}); }} className="w-full flex items-center gap-3 px-3 py-2 -mx-3 rounded-2xl text-left text-[13px] text-zinc-200 hover:bg-white/[0.05] hover:text-white">
              {work.kind === 'manga' ? <BookOpen size={14} className="text-zinc-500 shrink-0"/> : <Tv size={14} className="text-zinc-500 shrink-0"/>}
              <span className="flex-1 min-w-0 truncate">{work.title}</span><small className="text-[11px] text-zinc-500">{work.role}</small>
            </button>
          </li>)}</ul>
        </div>}
        <div className="kt-dossier-in flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
          <a href={browseHref('character', '', character.id, character.name)} className="inline-flex items-center gap-1 hover:text-white">Все появления героя<ExternalLink size={11}/></a>
          {character.sources?.map(s => <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-white">{s.name}<ExternalLink size={11}/></a>)}
        </div>
        {error && <p className="text-[12px] text-rose-300" role="alert">{error}</p>}
        {/* The design's row: arrows on the left, the bars on the right; only the drop animates. */}
        {count > 1 && <div className="mt-auto flex items-center justify-between gap-4 pt-4">
          <div className="flex gap-2">
            <button type="button" aria-label="Предыдущий персонаж" onClick={() => go(index - 1)} className="w-11 h-11 grid place-items-center rounded-full bg-white/[0.06] border border-white/[0.1] text-zinc-300 hover:text-white hover:bg-white/[0.12]"><ChevronLeft size={18}/></button>
            <button type="button" aria-label="Следующий персонаж" onClick={() => go(index + 1)} className="w-11 h-11 grid place-items-center rounded-full bg-white/[0.06] border border-white/[0.1] text-zinc-300 hover:text-white hover:bg-white/[0.12]"><ChevronRight size={18}/></button>
          </div>
          {count <= 20 ? <LiquidPager index={index} names={characters.map(c => c.name)} onPick={go} isNoir={isNoir}/> : <span className="font-mono text-[11px] tabular-nums text-zinc-400">{String(index + 1).padStart(2, '0')} / {count}</span>}
        </div>}
      </div>
    </div>
  </div></div>, document.body);
}
