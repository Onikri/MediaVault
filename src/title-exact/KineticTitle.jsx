import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { ArrowLeft } from 'lucide-react';
import { KineticSectionBlock } from './kinetic.jsx';
import { useKineticPagePhysics, LeftKineticNavigator, MobileChapterPill, IconPlay, IconBookmark, IconDownload, IconStar } from './kinetic-ui.jsx';
import './title-exact.css';
import {useKinetics} from './theme-mode.js';
import {setNavProgress} from './navbar/NavShell.jsx';

/* The title page of the approved design (motion lab title demo), markup and
   Tailwind classes kept as they are, filled with the real title: the full
   screen showcase (3D poster, monumental type, telemetry), the content card
   that slides over it with the real sections, the kinetic left navigator and
   the phone chapter pill. The navbar morph reads --nav-t published here. */

// Splits a title into the design's two lines: a light lead and a heavy tail.
function titleLines(name) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (words.length < 3) return ['', words.join(' ')];
  let best = 1, score = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(' ').length, b = words.slice(i).join(' ').length, s = Math.abs(a - b) + (a > b ? 4 : 0);
    if (s < score) { score = s; best = i; }
  }
  return [words.slice(0, best).join(' '), words.slice(best).join(' ')];
}

export default function KineticTitle({
  sections, isNoir = false, morphEnabled: morphAllowed = true,
  backdrop, nativeName, poster, posterTop, posterAge, posterKicker, posterTitle, sourceLabel, sourceDetail,
  kindLabel, seasonLabel, originalName, name, score, scoreSource, status, runtimeLabel, genres = [],
  description, cta, onTrailers, bookmark, share, onDownload, extraActions,
  episodes, ratings = [], facts = [], rating, onBack, backLabel, backId,
}) {
  // Кинетика lives in the profile menu (theme-mode store).
  const morphEnabled = useKinetics() && morphAllowed;
  const [heroMouse, setHeroMouse] = useState({ x: 0, y: 0 });
  const [posterTilt, setPosterTilt] = useState({ rx: 0, ry: 0, gx: 50, gy: 30, active: false });
  const [heroLoaded, setHeroLoaded] = useState(false);
  const [expandedSynopsis, setExpandedSynopsis] = useState(false);
  const [hoveredEpisode, setHoveredEpisode] = useState(null);
  const [hoverRating, setHoverRating] = useState(0);

  const heroRef = useRef(null);
  // Physics and navigation see only the chapter list; it changes only when sections come or go.
  const chapterKey = sections.map((s) => s.id + ':' + s.label).join('|');
  const chapters = useMemo(() => sections.map(({ node, ...chapter }) => chapter), [chapterKey]);
  const { activeId, smoothIndex, velocity, heroRatio, headerT, pastHero, navIntro, playerOffsetY } = useKineticPagePhysics(heroRef, chapters, 'title-watch-anchor');
  const activeIdx = Math.max(0, sections.findIndex((s) => s.id === activeId));
  const activeSection = sections[activeIdx] || sections[0];
  const [lightLine, heavyLine] = useMemo(() => titleLines(name), [name]);

  useEffect(() => {
    const id = window.requestAnimationFrame(() => setHeroLoaded(true));
    return () => window.cancelAnimationFrame(id);
  }, []);

  // The site navbar morphs with the same progress as the design's own bar.
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-title-exact', '');
    return () => { root.removeAttribute('data-title-exact'); setNavProgress(null); requestAnimationFrame(() => dispatchEvent(new Event('scroll'))); };
  }, []);
  useEffect(() => { setNavProgress(headerT); }, [headerT]);

  const scrollToSection = useCallback((id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  const handleHeroMouseMove = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    setHeroMouse({ x: ((e.clientX - rect.left) / rect.width - 0.5) * 2, y: ((e.clientY - rect.top) / rect.height - 0.5) * 2 });
  }, []);
  const handleHeroMouseLeave = useCallback(() => setHeroMouse({ x: 0, y: 0 }), []);
  const handlePosterMove = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const px = (e.clientX - rect.left) / rect.width, py = (e.clientY - rect.top) / rect.height;
    setPosterTilt({ rx: (0.5 - py) * 11, ry: (px - 0.5) * 13, gx: px * 100, gy: py * 100, active: true });
  }, []);
  const handlePosterLeave = useCallback(() => setPosterTilt({ rx: 0, ry: 0, gx: 50, gy: 30, active: false }), []);

  const cardTopRadius = Math.round(32 - heroRatio * 20);
  const clampedBgVel = Math.max(-0.7, Math.min(0.7, velocity));
  const bgWaveX = Math.sin(smoothIndex * 1.15) * 90;
  const bgWaveY = Math.cos(smoothIndex * 0.85) * 60;
  const heroContentFade = Math.max(0, 1 - heroRatio * 1.62);
  const heroTitleBlur = heroRatio > 0.08 ? Math.min(10, (heroRatio - 0.08) * 16) : 0;
  const watchId = sections[0]?.id;
  const shownRating = hoverRating || rating?.value || 0;

  return (
    <div data-theme={isNoir ? 'noir' : undefined} className="mv-tw kt-page">
    <div className={`min-h-screen text-white selection:bg-rose-600/40 selection:text-white transition-colors duration-500 ${isNoir ? 'bg-black' : 'bg-[#090608]'}`}>
      <style>{`
        @keyframes kineticFocusFloat {
          0%, 100% {
            transform: translate3d(0, 0px, 0);
          }
          50% {
            transform: translate3d(0, -3.5px, 0);
          }
        }
        .kinetic-focus-letter {
          animation: kineticFocusFloat 3.8s ease-in-out infinite;
          will-change: transform;
        }
        @keyframes heroBackdropKenBurns {
          0%, 100% {
            transform: scale(1.02) translate3d(0, 0, 0);
          }
          50% {
            transform: scale(1.065) translate3d(-1.2%, -0.8%, 0);
          }
        }
        /* One slow breath when the page opens, then the backdrop rests: an endless
           drift kept the GPU compositing the full-screen hero at 60 fps while idle. */
        .hero-backdrop-drift {
          animation: heroBackdropKenBurns 22s ease-in-out 1;
        }
        @keyframes heroScrollLine {
          0% {
            transform: translateY(-100%);
            opacity: 0;
          }
          35% {
            opacity: 1;
          }
          100% {
            transform: translateY(190%);
            opacity: 0;
          }
        }
        .hero-scroll-line {
          animation: heroScrollLine 2.3s cubic-bezier(0.4, 0, 0.2, 1) 4;
        }
        @keyframes mvDisc { to { transform: rotate(360deg); } }
        @keyframes mvEq { from { height: 25%; } to { height: 100%; } }
        @keyframes mvTrailer { from { width: 0%; } to { width: 100%; } }
        .hero-film-grain {
          background-image: radial-gradient(rgba(255, 255, 255, 0.045) 1px, transparent 0);
          background-size: 4px 4px;
        }
        .noir-dot-bg {
          background-image: radial-gradient(rgba(255, 255, 255, 0.14) 1px, transparent 1px);
          background-size: 16px 16px;
        }
        .content-corridor {
          width: 100%;
          padding-left: 1rem;
          padding-right: 1rem;
        }
        @media (min-width: 640px) {
          .content-corridor {
            padding-left: 2rem;
            padding-right: 2rem;
          }
        }
        @media (min-width: 768px) {
          .content-corridor {
            padding-left: 164px;
            padding-right: 2rem;
          }
        }
        @media (min-width: 1024px) {
          .content-corridor {
            padding-left: 204px;
            padding-right: 2.5rem;
          }
        }
        @media (min-width: 1280px) {
          .content-corridor {
            width: auto;
            max-width: 1320px;
            padding-left: 0;
            padding-right: 0;
            margin-left: max(224px, calc((100% - 1320px) / 2));
            margin-right: max(2.5rem, calc((100% - 1320px) / 2));
          }
        }
      `}</style>

      {/* Мягкая верхняя дымка поверх витрины под навбаром — тает вместе с морфом навбара */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-[60] h-28 bg-gradient-to-b from-black/75 via-black/30 to-transparent will-change-[opacity]"
        style={{ opacity: Number(Math.max(0, 1 - headerT * 1.15).toFixed(3)) }} />

      {/* ПОЛНОЭКРАННАЯ ВИТРИНА ТАЙТЛА */}
      <div ref={heroRef} onMouseMove={handleHeroMouseMove} onMouseLeave={handleHeroMouseLeave}
        className="kt-hero sticky top-0 h-screen w-full overflow-hidden flex flex-col justify-end z-0">
        <div className="absolute inset-0 will-change-transform transition-[filter] duration-200"
          style={{
            transform: `scale(${(1.01 + heroRatio * 0.09).toFixed(3)}) translate3d(${(heroMouse.x * -10).toFixed(1)}px, ${(heroMouse.y * -7).toFixed(1)}px, 0)`,
            filter: heroRatio > 0.04 ? `blur(${(heroRatio * 12).toFixed(1)}px) brightness(${(1 - heroRatio * 0.52).toFixed(2)})` : 'none',
          }}>
          <div className={`absolute inset-0 hero-backdrop-drift transition-opacity duration-1000 ${heroLoaded ? 'opacity-100' : 'opacity-0'}`}
            style={{ background: isNoir ? 'radial-gradient(ellipse 80% 70% at 64% 30%, rgba(255,255,255,0.12), #050505 68%)' : 'radial-gradient(ellipse 85% 75% at 66% 28%, rgba(225, 29, 72, 0.10) 0%, rgba(36, 13, 24, 0.30) 44%, #070508 100%)' }} />
          {backdrop && <div className={`absolute inset-0 hero-backdrop-drift kt-cover transition-opacity duration-1000 ${heroLoaded ? (isNoir ? 'opacity-60 grayscale' : 'opacity-90') : 'opacity-0'}`}>
            {backdrop}
          </div>}
          {!isNoir && (
            <>
              <div className="absolute top-[-10%] right-[8%] w-[52vw] h-[52vw] max-w-[760px] rounded-full blur-[150px] transition-colors duration-700" style={{ backgroundColor: 'rgba(244, 63, 94, 0.12)' }} />
              <div className="absolute bottom-[5%] left-[12%] w-[44vw] h-[44vw] max-w-[620px] rounded-full blur-[150px] transition-colors duration-700" style={{ backgroundColor: 'rgba(99, 102, 241, 0.08)' }} />
            </>
          )}
          <div className="absolute inset-0 hero-film-grain opacity-35 mix-blend-overlay pointer-events-none" />
          <div className="absolute inset-0 pointer-events-none" style={{ background: 'linear-gradient(180deg, rgba(6,4,6,0.68) 0%, rgba(6,4,6,0.12) 28%, rgba(8,5,8,0.48) 64%, rgba(9,5,8,0.96) 100%)' }} />
          <div className="absolute inset-0 pointer-events-none" style={{ background: 'linear-gradient(90deg, rgba(7,4,7,0.88) 0%, rgba(7,4,7,0.48) 42%, rgba(7,4,7,0.18) 68%, rgba(7,4,7,0.82) 100%)' }} />
        </div>

        <div className="pointer-events-none absolute inset-0 bg-[#080406] z-[5]" style={{ opacity: Number(Math.min(0.95, Math.pow(heroRatio, 1.2) * 0.95).toFixed(3)) }} />

        {nativeName && (
          <div className="hidden xl:block absolute right-8 top-24 z-[6] select-none pointer-events-none text-white/[0.05] font-light text-xl tracking-[0.55em] transition-all duration-1000"
            style={{ writingMode: 'vertical-rl', opacity: heroLoaded ? heroContentFade * 0.9 : 0, transform: `translate3d(${(heroMouse.x * 14).toFixed(1)}px, ${(heroMouse.y * 10 - heroRatio * 40).toFixed(1)}px, 0)` }}>
            {nativeName}
          </div>
        )}

        <div className="relative z-10 w-full max-w-[1520px] mx-auto px-5 sm:px-8 lg:px-12 pb-12 sm:pb-16 pt-24">
          <div className="grid grid-cols-1 lg:grid-cols-[216px_minmax(0,1fr)_280px] xl:grid-cols-[240px_minmax(0,1fr)_308px] gap-8 lg:gap-11 xl:gap-14 items-end">
            {/* КОЛОНКА 1: КОЛЛЕКЦИОННЫЙ 3D-ПОСТЕР СО СТЕКЛЯННЫМ БЛИКОМ */}
            <div className="hidden sm:flex flex-col gap-3.5 max-w-[240px] will-change-transform"
              style={{
                opacity: heroLoaded ? heroContentFade : 0,
                transform: heroLoaded ? `perspective(1000px) translate3d(${(heroMouse.x * 4).toFixed(1)}px, ${(heroRatio * 74).toFixed(1)}px, 0) scale(${(1 - heroRatio * 0.06).toFixed(3)}) rotateX(${(heroRatio * 8).toFixed(1)}deg)` : 'translate3d(0, 32px, 0) scale(0.96)',
                transition: heroRatio === 0 ? 'opacity 900ms cubic-bezier(0.16, 1, 0.3, 1) 120ms, transform 1000ms cubic-bezier(0.16, 1, 0.3, 1) 120ms' : 'none',
              }}>
              <div onMouseMove={handlePosterMove} onMouseLeave={handlePosterLeave}
                className="relative aspect-[2/3] w-full rounded-[20px] p-[1px] bg-gradient-to-b from-white/25 via-white/10 to-white/5 shadow-[0_32px_80px_-12px_rgba(0,0,0,0.92)] cursor-pointer will-change-transform"
                style={{
                  transform: `perspective(900px) rotateX(${posterTilt.rx.toFixed(2)}deg) rotateY(${posterTilt.ry.toFixed(2)}deg) scale(${posterTilt.active ? 1.02 : 1})`,
                  transition: posterTilt.active ? 'transform 120ms ease-out' : 'transform 500ms cubic-bezier(0.16, 1, 0.3, 1)',
                }}>
                <div className="relative w-full h-full rounded-[19px] overflow-hidden bg-[#110a0e] flex flex-col justify-between p-4">
                  <div className="absolute inset-0" style={{ background: isNoir ? 'linear-gradient(160deg, #27272a 0%, #09090b 65%, #000 100%)' : 'radial-gradient(circle at 75% 18%, rgba(225,29,72,0.42), transparent 55%), linear-gradient(165deg, #24111a 0%, #120b10 55%, #070507 100%)' }} />
                  <div className={`absolute inset-0 kt-poster-art ${isNoir ? 'grayscale opacity-80' : ''}`}>{poster}</div>
                  <div className="pointer-events-none absolute inset-0 transition-opacity duration-300"
                    style={{ opacity: posterTilt.active ? 0.55 : 0.16, background: `radial-gradient(circle at ${posterTilt.gx.toFixed(0)}% ${posterTilt.gy.toFixed(0)}%, rgba(255,255,255,0.28), transparent 58%)` }} />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-transparent to-black/20 pointer-events-none" />
                  <div className="relative z-10 flex items-center justify-between">
                    <span className="text-[10px] font-mono tracking-[0.18em] uppercase text-white/75">{posterTop}</span>
                    {posterAge && <span className="px-1.5 py-0.5 rounded bg-black/45 backdrop-blur-md text-[10px] font-mono text-white/80 border border-white/10">{posterAge}</span>}
                  </div>
                  <div className="relative z-10 space-y-1">
                    {posterKicker && <p className="text-[9px] font-mono uppercase tracking-[0.24em] text-rose-300/80">{posterKicker}</p>}
                    <p className="text-[15px] font-bold leading-snug tracking-tight text-white">{posterTitle}</p>
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between px-1 text-[11px] text-zinc-400">
                <span className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
                  <span>{sourceLabel}</span>
                </span>
                {sourceDetail && <span className="font-mono text-[10px] text-zinc-500">{sourceDetail}</span>}
              </div>
            </div>

            {/* КОЛОНКА 2: МОНУМЕНТАЛЬНАЯ ТИПОГРАФИКА, КИНО-МЕТА И ДЕЙСТВИЯ */}
            <div className="flex flex-col justify-end space-y-6 pb-1 will-change-transform"
              style={{ opacity: heroContentFade, transform: `translate3d(0, ${(heroRatio * 36).toFixed(1)}px, 0)`, filter: heroTitleBlur > 0.1 ? `blur(${heroTitleBlur.toFixed(1)}px)` : 'none' }}>
              <div className="flex flex-wrap items-center gap-3 text-[11px] uppercase tracking-[0.22em] text-zinc-300/80"
                style={{ opacity: heroLoaded ? 1 : 0, transform: heroLoaded ? 'translate3d(0,0,0)' : 'translate3d(0,14px,0)', transition: 'all 750ms cubic-bezier(0.16, 1, 0.3, 1) 80ms' }}>
                {onBack && <button type="button" id={backId} onClick={onBack} aria-label={backLabel} title={backLabel}
                  className="-ml-1 w-7 h-7 rounded-full bg-white/[0.06] hover:bg-white/[0.14] border border-white/[0.1] flex items-center justify-center text-zinc-300 hover:text-white transition-all normal-case tracking-normal">
                  <ArrowLeft size={14} aria-hidden="true" />
                </button>}
                <span className="inline-flex items-center gap-2 text-rose-400 font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-500 shadow-[0_0_10px_#e11d48]" />
                  {kindLabel}
                </span>
                {seasonLabel && <><span className="h-[1px] w-7 bg-white/20 origin-left" /><span>{seasonLabel}</span></>}
                {originalName && <><span className="hidden sm:inline text-white/25">·</span>
                  <span className="hidden sm:inline normal-case tracking-[0.04em] text-zinc-400 font-normal" translate="no">{originalName}</span></>}
              </div>

              <h1 className="space-y-0.5 select-none" translate="no" style={{ letterSpacing: `${(-0.03 + heroRatio * 0.045).toFixed(3)}em` }}>
                {lightLine && <span className="block overflow-hidden pb-1">
                  <span className="block text-3xl sm:text-4xl xl:text-[46px] font-light tracking-[-0.02em] leading-[1.08] text-white/85"
                    style={{ transform: heroLoaded ? 'translate3d(0,0,0)' : 'translate3d(0,115%,0)', transition: 'transform 950ms cubic-bezier(0.16, 1, 0.3, 1) 140ms' }}>
                    {lightLine}
                  </span>
                </span>}
                {lightLine && ' '}
                <span className="block overflow-hidden pb-1.5">
                  <span className="block text-4xl sm:text-6xl xl:text-[68px] font-black leading-[0.98] text-white drop-shadow-[0_14px_40px_rgba(0,0,0,0.55)]"
                    style={{ transform: heroLoaded ? 'translate3d(0,0,0)' : 'translate3d(0,115%,0)', transition: 'transform 1050ms cubic-bezier(0.16, 1, 0.3, 1) 240ms' }}>
                    {heavyLine}
                  </span>
                </span>
              </h1>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-zinc-300"
                style={{ opacity: heroLoaded ? 1 : 0, transform: heroLoaded ? 'translate3d(0,0,0)' : 'translate3d(0,16px,0)', transition: 'all 800ms cubic-bezier(0.16, 1, 0.3, 1) 340ms' }}>
                {score && <>
                  <span className="inline-flex items-center gap-1.5 text-white font-semibold tabular-nums">
                    <IconStar size={13} filled className="text-rose-500" />
                    <span>{score}</span>
                    <span className="text-[11px] font-normal text-zinc-400">{scoreSource}</span>
                  </span>
                  <span className="h-3.5 w-[1px] bg-white/15" />
                </>}
                {status && <><span className="text-zinc-200">{status}</span><span className="h-3.5 w-[1px] bg-white/15" /></>}
                {runtimeLabel && <span className="tabular-nums text-zinc-300">{runtimeLabel}</span>}
                {genres.length > 0 && <><span className="h-3.5 w-[1px] bg-white/15 hidden sm:inline-block" />
                  <span className="text-zinc-400 hidden sm:inline">{genres.slice(0, 3).join(' · ')}</span></>}
              </div>

              <div className="max-w-xl space-y-2"
                style={{ opacity: heroLoaded ? 1 : 0, transform: heroLoaded ? 'translate3d(0,0,0)' : 'translate3d(0,18px,0)', transition: 'all 850ms cubic-bezier(0.16, 1, 0.3, 1) 420ms' }}>
                <p id="titleSummary" translate="no" className={`text-[14px] sm:text-[15px] text-zinc-300/85 leading-[1.7] transition-all ${expandedSynopsis ? '' : 'line-clamp-3'}`}>{description}</p>
                <button type="button" onClick={() => setExpandedSynopsis((v) => !v)}
                  className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-400 hover:text-white transition-colors">
                  {expandedSynopsis ? 'Свернуть описание' : 'Полное описание'}
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-3 pt-1"
                style={{ opacity: heroLoaded ? 1 : 0, transform: heroLoaded ? 'translate3d(0,0,0)' : 'translate3d(0,20px,0)', transition: 'all 900ms cubic-bezier(0.16, 1, 0.3, 1) 500ms' }}>
                {cta && <button type="button" onClick={cta.onClick} disabled={cta.disabled}
                  className={`group relative overflow-hidden h-12 pl-6 pr-5 rounded-full text-[13px] font-semibold flex items-center gap-3 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] ${isNoir ? 'bg-white text-black shadow-[0_14px_40px_rgba(255,255,255,0.22)]' : 'bg-rose-600 hover:bg-rose-500 text-white shadow-[0_14px_42px_rgba(225,29,72,0.48)]'}`}>
                  {cta.icon || <IconPlay size={14} filled />}
                  <span>{cta.label}</span>
                  {cta.time && <span className={`pl-2.5 border-l text-[11px] font-mono tabular-nums ${isNoir ? 'border-black/20 text-black/65' : 'border-white/25 text-rose-100/90'}`}>{cta.time}</span>}
                  {cta.progress > 0 && <span className={`absolute bottom-0 left-0 h-[2.5px] ${isNoir ? 'bg-black/45' : 'bg-white/70'}`} style={{ width: `${Math.round(Math.min(1, cta.progress) * 100)}%` }} />}
                </button>}
                {onTrailers && <button type="button" onClick={onTrailers}
                  className="h-12 px-5 rounded-full bg-white/[0.06] hover:bg-white/[0.13] border border-white/[0.12] hover:border-white/25 backdrop-blur-md text-[13px] font-medium text-white/90 transition-all">
                  Трейлеры
                </button>}
                <div className="flex items-center gap-2 ml-1 kt-round-actions">
                  {bookmark && <button type="button" aria-label={bookmark.on ? 'Убрать тайтл из избранного' : 'В избранное'} aria-pressed={bookmark.on} onClick={bookmark.toggle}
                    className={`w-11 h-11 rounded-full border backdrop-blur-md flex items-center justify-center transition-all ${bookmark.on ? (isNoir ? 'bg-white text-black border-white' : 'bg-rose-500/20 border-rose-400/45 text-rose-300') : 'bg-white/[0.05] border-white/[0.1] text-zinc-300 hover:bg-white/[0.12] hover:text-white'}`}>
                    <IconBookmark size={15} />
                  </button>}
                  {share}
                  {onDownload && <button type="button" aria-label="Скачать текущий файл" title="Скачать текущий файл" onClick={onDownload}
                    className="w-11 h-11 rounded-full bg-white/[0.05] hover:bg-white/[0.12] border border-white/[0.1] backdrop-blur-md flex items-center justify-center text-zinc-300 hover:text-white transition-all">
                    <IconDownload size={15} />
                  </button>}
                  {extraActions}
                </div>
              </div>
            </div>

            {/* КОЛОНКА 3: БЕЗРАМОЧНАЯ АРХИТЕКТУРНАЯ ТЕЛЕМЕТРИЯ MEDIAVAULT */}
            <div className="hidden lg:flex flex-col gap-6 pb-1 pl-6 border-l border-white/[0.09] will-change-transform"
              style={{
                opacity: heroLoaded ? heroContentFade : 0,
                transform: heroLoaded ? `translate3d(0, ${(heroRatio * 56).toFixed(1)}px, 0)` : 'translate3d(18px, 0, 0)',
                transition: heroRatio === 0 ? 'opacity 950ms cubic-bezier(0.16, 1, 0.3, 1) 300ms, transform 1000ms cubic-bezier(0.16, 1, 0.3, 1) 300ms' : 'none',
              }}>
              {episodes && episodes.total > 0 && (
                <div className="space-y-3">
                  <div className="flex items-baseline justify-between">
                    <div className="flex items-baseline gap-2">
                      <span className="text-3xl font-light tracking-tight tabular-nums text-white">{episodes.total}</span>
                      <span className="text-[11px] uppercase tracking-[0.18em] text-zinc-400">{episodes.unit}</span>
                    </div>
                    <span className="text-[11px] font-mono tabular-nums text-rose-300/90">
                      {hoveredEpisode ? `${episodes.word} ${hoveredEpisode}` : `${episodes.current || 0} / ${episodes.total}`}
                    </span>
                  </div>
                  <div className="grid gap-1.5 items-end h-7" style={{ gridTemplateColumns: `repeat(${Math.min(48, episodes.total)}, minmax(0, 1fr))` }} onMouseLeave={() => setHoveredEpisode(null)}>
                    {Array.from({ length: Math.min(48, episodes.total) }).map((_, i) => {
                      const ep = i + 1, watched = ep <= (episodes.current || 0), released = ep <= (episodes.released ?? episodes.total), isHovered = hoveredEpisode === ep;
                      return <button key={ep} type="button" aria-label={`${episodes.word} ${ep}`} disabled={!released}
                        onMouseEnter={() => setHoveredEpisode(ep)} onClick={() => episodes.onPick?.(ep)}
                        className={`w-full rounded-[2px] transition-all duration-200 ${isHovered && released ? (isNoir ? 'h-7 bg-white' : 'h-7 bg-rose-400 shadow-[0_0_12px_rgba(244,63,94,0.8)]') : watched ? (isNoir ? 'h-5 bg-white/85' : 'h-5 bg-rose-500/90') : released ? 'h-3 bg-white/15 hover:bg-white/40' : 'h-2 bg-white/[0.06]'}`} />;
                    })}
                  </div>
                </div>
              )}

              {ratings.length > 0 && (
                <div className={`grid grid-cols-3 gap-4 ${episodes?.total ? 'pt-5 border-t border-white/[0.08]' : ''}`}>
                  {ratings.slice(0, 3).map((r) => {
                    const body = <>
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: r.rgb ? `rgb(${r.rgb})` : '#34d399' }} />
                        <span className="text-base font-bold tabular-nums text-white leading-none">{r.value}</span>
                      </div>
                      <p className="text-[10px] uppercase tracking-[0.14em] text-zinc-500">{r.name}</p>
                    </>;
                    return r.url ? <a key={r.key} href={r.url} target="_blank" rel="noopener noreferrer" className="space-y-1 hover:opacity-80 transition-opacity">{body}</a> : <div key={r.key} className="space-y-1">{body}</div>;
                  })}
                </div>
              )}

              {facts.length > 0 && (
                <div className="space-y-2 pt-5 border-t border-white/[0.08] text-[12px]">
                  {facts.map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-3">
                      <span className="text-zinc-500 shrink-0">{label}</span>
                      <span className="text-zinc-200 font-medium text-right kt-fact">{value}</span>
                    </div>
                  ))}
                </div>
              )}

              {rating && (
                <div className="pt-5 border-t border-white/[0.08] space-y-2.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="uppercase tracking-[0.18em] text-zinc-500">Твоя оценка</span>
                    <span className="font-mono font-semibold tabular-nums text-white">{shownRating || '—'}<span className="text-zinc-500">/10</span></span>
                  </div>
                  <div className="grid grid-cols-10 gap-1" role="group" aria-label="Оценить произведение" onMouseLeave={() => setHoverRating(0)}>
                    {Array.from({ length: 10 }).map((_, i) => {
                      const val = i + 1, isFilled = val <= shownRating;
                      return <button key={val} type="button" aria-label={'Оценка ' + val} aria-pressed={rating.value === val} disabled={rating.disabled}
                        onMouseEnter={() => setHoverRating(val)} onClick={() => rating.onRate(val)} className="group flex flex-col items-center gap-1.5 py-1">
                        <span className={`text-[10px] font-mono tabular-nums transition-colors ${val === shownRating ? 'text-white font-bold' : isFilled ? 'text-zinc-300' : 'text-zinc-600 group-hover:text-zinc-300'}`}>{val}</span>
                        <span className={`h-[2px] w-full rounded-full transition-all ${isFilled ? (isNoir ? 'bg-white' : 'bg-rose-500 shadow-[0_0_8px_rgba(225,29,72,0.7)]') : 'bg-white/10 group-hover:bg-white/30'}`} />
                      </button>;
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Нижняя редакционная полоса витрины */}
          <div className="mt-10 pt-4 border-t border-white/[0.07] flex items-center justify-between gap-4"
            style={{ opacity: heroLoaded ? Math.max(0, 1 - heroRatio * 3.2) : 0, pointerEvents: heroRatio > 0.25 ? 'none' : 'auto', transition: heroRatio === 0 ? 'opacity 900ms ease 620ms' : 'none' }}>
            <button type="button" onClick={() => scrollToSection(watchId)}
              className="group flex items-center gap-3 text-[10px] font-mono uppercase tracking-[0.26em] text-zinc-400 hover:text-white transition-colors">
              <span className="relative w-[1px] h-5 bg-white/20 overflow-hidden">
                <span className="hero-scroll-line absolute inset-x-0 top-0 h-2.5 bg-gradient-to-b from-transparent via-rose-400 to-white" />
              </span>
              <span>{sections[0]?.label === 'Читать' ? 'Спуститься к чтению' : 'Спуститься к просмотру'}</span>
            </button>
            <span className="hidden sm:inline text-[10px] font-mono tracking-[0.16em] text-zinc-500 uppercase">{sections.length} {sections.length === 1 ? 'глава' : sections.length < 5 ? 'главы' : 'глав'}</span>
          </div>
        </div>
      </div>

      {/* ОСНОВНАЯ КАРТОЧКА КОНТЕНТА (НАЕЗЖАЕТ НА ВИТРИНУ И УЧАСТВУЕТ В МОРФЕ) */}
      <main className={`relative z-10 min-h-screen border-t shadow-[0_-30px_90px_rgba(0,0,0,0.88)] overflow-x-clip transition-colors duration-500 ${isNoir ? 'bg-[#050505] border-white/20 noir-dot-bg' : 'bg-[#12090d] border-white/[0.08]'}`}
        style={{ borderTopLeftRadius: `${Math.max(0, cardTopRadius)}px`, borderTopRightRadius: `${Math.max(0, cardTopRadius)}px` }}>
        <div className={`pointer-events-none fixed inset-0 z-0 overflow-hidden transition-opacity duration-700 ${pastHero ? 'opacity-100' : 'opacity-0'}`}>
          {!isNoir && (
            <>
              <div className="absolute -top-28 left-[18%] w-[680px] h-[680px] rounded-full blur-[160px] transition-colors duration-700 will-change-transform"
                style={{ backgroundColor: activeSection?.glowPrimary, transform: morphEnabled ? `translate3d(${bgWaveX.toFixed(1)}px, ${(bgWaveY + clampedBgVel * 110).toFixed(1)}px, 0) scale(${(1 + Math.abs(clampedBgVel) * 0.22).toFixed(3)})` : 'none' }} />
              <div className="absolute bottom-[-10%] right-[12%] w-[620px] h-[620px] rounded-full blur-[160px] transition-colors duration-700 will-change-transform"
                style={{ backgroundColor: activeSection?.glowSecondary, transform: morphEnabled ? `translate3d(${(-bgWaveX * 0.85).toFixed(1)}px, ${(-bgWaveY * 0.7 - clampedBgVel * 95).toFixed(1)}px, 0) scale(${(1 + Math.abs(clampedBgVel) * 0.18).toFixed(3)})` : 'none' }} />
            </>
          )}
          <div className={`absolute right-6 lg:right-14 top-1/2 -translate-y-1/2 font-black tracking-tighter leading-none select-none will-change-transform ${isNoir ? 'font-mono text-white/[0.04]' : 'font-sans text-white/[0.032]'}`}
            style={{
              fontSize: 'clamp(160px, 24vw, 340px)',
              transform: morphEnabled ? `translate3d(0, calc(-50% + ${(clampedBgVel * 120).toFixed(1)}px), 0) scale(${(1 + Math.abs(clampedBgVel) * 0.08).toFixed(3)})` : 'translate3d(0, -50%, 0)',
              filter: morphEnabled && Math.abs(clampedBgVel) > 0.05 ? `blur(${Math.min(10, Math.abs(clampedBgVel) * 14).toFixed(1)}px)` : 'none',
            }}>
            0{activeIdx + 1}
          </div>
        </div>

        <div className="content-corridor relative z-10 pt-14 pb-36 space-y-28">
          {sections.map((section, index) => (
            <KineticSectionBlock key={section.id} id={section.id} sectionIndex={index} enabled={morphEnabled && !section.still} isNoir={isNoir}>
              {section.id === watchId ? <div id="title-watch-anchor" className="kt-watch">{section.node}</div> : section.node}
            </KineticSectionBlock>
          ))}
        </div>
      </main>

      <LeftKineticNavigator sections={chapters} playerId="title-watch-anchor" activeId={activeId} onSelect={scrollToSection} smoothIndex={smoothIndex} velocity={velocity}
        navIntro={navIntro} playerOffsetY={playerOffsetY} visible={pastHero} mode={isNoir ? 'noir-matrix' : 'cinema-dof'} />
      <MobileChapterPill sections={chapters} activeId={activeId} onSelect={scrollToSection} visible={pastHero} />
    </div>
    </div>
  );
}
