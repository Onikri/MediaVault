import { useState, useEffect, useRef } from 'react';
import { publishPhysics } from './kinetic.jsx';

/* Kinetic chapter UI of the title page, verbatim from the approved design
   (motion lab title demo): page physics, the vertical letter typography, the
   refined progress rail, the left navigator and the phone chapter pill. The
   only change is that the chapters come in as \`sections\` (the title's real
   sections) instead of a fixed list. */

const SvgIcon = ({ size = 18, className = '', children, fill = 'none' }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill={fill}
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
  >
    {children}
  </svg>
);

export const IconPlay = ({ size = 18, className = '', filled = false }) => (
  <SvgIcon size={size} className={className} fill={filled ? 'currentColor' : 'none'}>
    <polygon points="6 3 20 12 6 21 6 3" />
  </SvgIcon>
);

export const IconBookmark = ({ size = 16, className = '' }) => (
  <SvgIcon size={size} className={className}>
    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
  </SvgIcon>
);

export const IconShare = ({ size = 16, className = '' }) => (
  <SvgIcon size={size} className={className}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
  </SvgIcon>
);

export const IconDownload = ({ size = 16, className = '' }) => (
  <SvgIcon size={size} className={className}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </SvgIcon>
);

export const IconStar = ({ size = 14, className = '', filled = false }) => (
  <SvgIcon size={size} className={className} fill={filled ? 'currentColor' : 'none'}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </SvgIcon>
);

export const IconChevronUp = ({ size = 16, className = '' }) => (
  <SvgIcon size={size} className={className}>
    <polyline points="18 15 12 9 6 15" />
  </SvgIcon>
);

/**
 * Нейтральные световые пресеты для проверки витрины поверх разных тонов реального баннера/видео.
 */

export function useKineticPagePhysics(heroRef, sections, playerId = 'watch-player') {
  const [state, setState] = useState({
    activeId: sections[0]?.id,
    smoothIndex: 0,
    velocity: 0,
    heroRatio: 0,
    headerT: 0,
    pastHero: false,
    navIntro: 0,
    playerOffsetY: 0,
  });

  const smoothIndexRef = useRef(0);
  const velocityRef = useRef(0);
  const headerTRef = useRef(0);
  const lastScrollYRef = useRef(0);

  useEffect(() => {
    let rafId = null;

    const tick = () => {
      try {
        const scrollY = window.scrollY || window.pageYOffset || 0;
        const viewportH = window.innerHeight || 800;

        // 1. Уход витрины и точная привязка появления «СМОТРЕТЬ» к реальному положению плеера
        let heroRatio = 0;
        let pastHero = false;
        let navIntro = 0;
        let playerOffsetY = 0;

        if (heroRef.current) {
          const heroHeight = heroRef.current.offsetHeight || viewportH;
          heroRatio = Math.max(0, Math.min(1, scrollY / (heroHeight * 0.85)));

          const playerEl = document.getElementById(playerId);
          if (playerEl) {
            const pRect = playerEl.getBoundingClientRect();
            const playerCenterY = pRect.top + pRect.height * 0.5;

            // Пока плеер поднимается к центру экрана, типографика физически держится на его уровне
            playerOffsetY = Math.max(
              0,
              Math.min(viewportH * 0.34, playerCenterY - viewportH * 0.5)
            );

            // Появляется ровно когда плеер входит в основную рабочую зону,
            // и собирается в 100% фокус к моменту выравнивания плеера на экране
            const triggerStart = viewportH * 0.62;
            const triggerFull = viewportH * 0.22;
            pastHero = pRect.top < triggerStart;
            navIntro = Math.max(
              0,
              Math.min(1, (triggerStart - pRect.top) / Math.max(1, triggerStart - triggerFull))
            );
          } else {
            pastHero = scrollY >= heroHeight * 0.6;
            navIntro = Math.max(
              0,
              Math.min(1, (scrollY - heroHeight * 0.6) / (heroHeight * 0.3))
            );
          }
        }

        // Непрерывный демпфированный прогресс трансформации навбара (0 на витрине → 1 при наезде карточки)
        const rawHeader = Math.max(0, Math.min(1, (heroRatio - 0.08) / 0.68));
        const targetHeaderT = rawHeader * rawHeader * (3 - 2 * rawHeader); // smoothstep
        headerTRef.current += (targetHeaderT - headerTRef.current) * 0.2;
        if (Math.abs(targetHeaderT - headerTRef.current) < 0.0008) {
          headerTRef.current = targetHeaderT;
        }

        // 2. Вычисление непрерывного индекса главы по положению разделов
        const anchorY = viewportH * 0.34;
        const rects = sections.map((sec) => {
          const el = document.getElementById(sec.id);
          return el ? el.getBoundingClientRect().top : 0;
        });

        let targetIndex = 0;
        if (rects[0] >= anchorY) {
          targetIndex = 0;
        } else if (rects[rects.length - 1] <= anchorY) {
          targetIndex = sections.length - 1;
        } else {
          for (let i = 0; i < rects.length - 1; i++) {
            const curr = rects[i];
            const next = rects[i + 1];
            if (curr <= anchorY && next > anchorY) {
              const span = Math.max(1, next - curr);
              const t = (anchorY - curr) / span;
              targetIndex = i + Math.max(0, Math.min(1, t));
              break;
            }
          }
        }

        // 3. Мягкая пружинная инерция и сглаженная скорость скролла
        const deltaScroll = scrollY - lastScrollYRef.current;
        lastScrollYRef.current = scrollY;

        const rawVel = Math.max(-1.35, Math.min(1.35, deltaScroll / 38));
        velocityRef.current += (rawVel - velocityRef.current) * 0.15;
        if (Math.abs(velocityRef.current) < 0.0006) velocityRef.current = 0;

        smoothIndexRef.current += (targetIndex - smoothIndexRef.current) * 0.17;

        const clampedSmooth = Math.max(0, Math.min(sections.length - 1, smoothIndexRef.current));
        // Section wrappers and cards read these directly (no React render per frame).
        publishPhysics(clampedSmooth, velocityRef.current);
        const activeIdx = Math.min(
          sections.length - 1,
          Math.max(0, Math.floor(clampedSmooth + 0.32))
        );

        setState((prev) => {
          const changed =
            prev.activeId !== sections[activeIdx].id ||
            Math.abs(prev.smoothIndex - clampedSmooth) > 0.001 ||
            Math.abs(prev.velocity - velocityRef.current) > 0.0012 ||
            Math.abs(prev.heroRatio - heroRatio) > 0.004 ||
            Math.abs(prev.headerT - headerTRef.current) > 0.002 ||
            prev.pastHero !== pastHero ||
            Math.abs(prev.navIntro - navIntro) > 0.004 ||
            Math.abs(prev.playerOffsetY - playerOffsetY) > 0.5;

          if (!changed) return prev;
          return {
            activeId: sections[activeIdx].id,
            smoothIndex: clampedSmooth,
            velocity: velocityRef.current,
            heroRatio,
            headerT: headerTRef.current,
            pastHero,
            navIntro,
            playerOffsetY,
          };
        });
      } catch (err) {
        // Игнорируем временные ошибки измерения DOM при перестроении
      }

      rafId = window.requestAnimationFrame(tick);
    };

    rafId = window.requestAnimationFrame(tick);
    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
    };
  }, [heroRef, sections, playerId]);

  return state;
}

/**
 * Подбор крупного, но аккуратного вертикального кегля под длину слова.
 */
export function getVerticalTypographySize(labelText, mode) {
  const isNoir = mode === 'noir-matrix';
  const fontFamily = isNoir ? 'font-mono' : 'font-sans';

  if (labelText.length >= 9) {
    return `${fontFamily} text-[36px] lg:text-[46px] xl:text-[54px] 2xl:text-[62px] font-black leading-[0.86] tracking-tight`;
  }
  if (labelText.length >= 7) {
    return `${fontFamily} text-[42px] lg:text-[54px] xl:text-[64px] 2xl:text-[72px] font-black leading-[0.86] tracking-tight`;
  }
  return `${fontFamily} text-[48px] lg:text-[62px] xl:text-[72px] 2xl:text-[82px] font-black leading-[0.85] tracking-tight`;
}

/**
 * Обновлённая вертикальная побуквенная типографика (на левом краю):
 * 1. Первичная сборка (`navIntro`) — после ухода витрины первая глава мягко собирается.
 * 2. Сборка следующей главы (`delta < -0.02`) — шёлковый каскад сверху с 3D-разворотом.
 * 3. В фокусе (`-0.02 .. +0.58`) — 100% чёткость, световой блик чтения и инерция по весу.
 * 4. Уход (`delta > +0.58`) — плавный весовой водопад вниз с расслоением по Z-глубине и DoF-блюром.
 */
export function VerticalKineticTypography({ sections, smoothIndex, velocity, navIntro = 1, mode = 'cinema-dof' }) {
  return (
    <div
      className="relative h-[70vh] min-h-[460px] max-h-[780px] w-14 lg:w-[70px] xl:w-[84px] 2xl:w-[96px] select-none pointer-events-none"
      style={{
        perspective: '1200px',
        maskImage:
          'linear-gradient(to bottom, transparent 0%, black 11%, black 89%, transparent 100%)',
        WebkitMaskImage:
          'linear-gradient(to bottom, transparent 0%, black 11%, black 89%, transparent 100%)',
      }}
    >
      {sections.map((section, secIdx) => {
        const delta = smoothIndex - secIdx;
        if (delta < -0.45 || delta > 1.0) return null;

        const labelText = section.verticalLabel;
        const chars = Array.from(labelText);
        const totalChars = chars.length;
        const sizeClass = getVerticalTypographySize(labelText, mode);

        // Для первой главы используем navIntro, чтобы текст шёлково собирался ровно на уровне плеера
        const firstChapterIntroT = secIdx === 0 ? Math.max(0, 1 - navIntro) : 0;
        const isIntroPhase = secIdx === 0 && firstChapterIntroT > 0.005 && delta <= 0.45;

        const isEntering = isIntroPhase || delta < -0.02;
        const isFocus = !isIntroPhase && delta >= -0.02 && delta <= 0.58;
        const isExiting = !isIntroPhase && delta > 0.58;

        const rawEnterT = isIntroPhase
          ? firstChapterIntroT
          : isEntering
          ? Math.min(1, Math.abs(delta + 0.02) / 0.4)
          : 0;
        const holdProgress = isFocus
          ? Math.min(1, Math.max(0, (delta + 0.02) / 0.6))
          : isExiting
          ? 1
          : 0;
        const rawExitT = isExiting ? Math.min(1, (delta - 0.58) / 0.4) : 0;

        return (
          <div
            key={section.id}
            className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 lg:gap-1"
            style={{ transformStyle: 'preserve-3d' }}
          >
            {chars.map((char, idx) => {
              const charRatio = totalChars > 1 ? idx / (totalChars - 1) : 0;
              const seed = (idx * 37 + secIdx * 23 + 11) % 100;
              const weight = 0.72 + (seed / 100) * 0.68;
              const depthLayer = ((idx * 17 + secIdx * 7) % 3) - 1;
              const clampedVel = Math.max(-0.6, Math.min(0.6, velocity));

              let xOffset = 0;
              let yOffset = 0;
              let zOffset = 0;
              let scale = 1;
              let rotateX = 0;
              let rotateY = 0;
              let skewY = 0;
              let blurPx = 0;
              let opacity = 1;
              let waveBoost = 0;

              if (isEntering) {
                const stagger = (1 - charRatio) * 0.3;
                const localT = Math.max(
                  0,
                  Math.min(1, (rawEnterT - stagger * 0.52) / (1 - stagger * 0.52))
                );
                const eased = localT * localT * (3 - 2 * localT);
                const weighted = eased * weight;

                const kerningSpread = (charRatio - 0.5) * 44 * eased;
                yOffset =
                  -weighted * (96 + depthLayer * 30) -
                  kerningSpread +
                  clampedVel * weight * 42;
                xOffset = -eased * (16 - depthLayer * 7);
                zOffset = depthLayer * eased * 55;
                scale = Math.max(0.74, 1 - eased * 0.13 + depthLayer * eased * 0.14);
                rotateX = eased * 32;
                rotateY = -eased * 14;
                skewY = -eased * 3.2;
                blurPx = Math.min(13, weighted * (7.5 + Math.abs(depthLayer) * 4.2));
                opacity = Math.max(0, 1 - Math.pow(localT, 1.25));
              } else if (isFocus) {
                const distToWave = Math.abs(holdProgress - charRatio);
                waveBoost = Math.max(0, 1 - distToWave * 2.5);
                const smoothWave = waveBoost * waveBoost * (3 - 2 * waveBoost);

                yOffset = clampedVel * weight * 22;
                xOffset = smoothWave * 6.5;
                zOffset = smoothWave * 18;
                scale = 1 + smoothWave * 0.068;
                rotateX = clampedVel * 7;
                rotateY = smoothWave * 6;
                skewY = clampedVel * 2.1;
                blurPx = 0;
                opacity = 0.87 + smoothWave * 0.13;
              } else {
                const stagger = charRatio * 0.28;
                const localT = Math.max(
                  0,
                  Math.min(1, (rawExitT - stagger * 0.46) / (1 - stagger * 0.46))
                );
                const eased = Math.pow(localT, 1.38);
                const weighted = eased * weight;

                const kerningDrift = (charRatio - 0.5) * 36 * eased;
                yOffset =
                  weighted * (132 + depthLayer * 42) +
                  kerningDrift +
                  clampedVel * weight * 88;
                xOffset = -weighted * (14 - depthLayer * 9);
                zOffset = depthLayer * weighted * 65;
                scale = Math.max(0.64, 1 + depthLayer * weighted * 0.22 - eased * 0.11);
                rotateX = -eased * 30;
                rotateY = eased * 12;
                skewY = eased * 4;
                const blurBase = mode === 'cinema-dof' ? 11 : 7.8;
                blurPx = Math.min(16, weighted * (blurBase + Math.abs(depthLayer) * 4.8));
                opacity = Math.max(0, 1 - Math.pow(localT, 1.28));
              }

              let textColor = 'text-white/95';
              if (!isFocus && depthLayer === -1) {
                textColor = mode === 'noir-matrix' ? 'text-white/45' : 'text-zinc-400';
              } else if (isFocus && waveBoost > 0.42 && mode !== 'noir-matrix') {
                textColor = 'text-rose-100';
              }

              let textShadow = '0 10px 28px rgba(0,0,0,0.48)';
              if (isFocus && waveBoost > 0.18 && mode !== 'noir-matrix') {
                textShadow = `0 0 ${(waveBoost * 26).toFixed(0)}px rgba(225,29,72,${(
                  waveBoost * 0.72
                ).toFixed(2)})`;
              } else if (mode === 'cinema-dof' && !isFocus) {
                const shift = Math.min(7, (rawEnterT + rawExitT) * 7.5);
                textShadow = `${shift}px 0 0 rgba(225,29,72,0.52), ${-shift}px 0 0 rgba(255,255,255,0.22)`;
              }

              return (
                <span
                  key={idx}
                  className={`inline-block will-change-transform ${sizeClass} ${textColor}`}
                  style={{
                    transform: `translate3d(${xOffset.toFixed(1)}px, ${yOffset.toFixed(1)}px, ${zOffset.toFixed(1)}px) scale(${scale.toFixed(3)}) rotateX(${rotateX.toFixed(1)}deg) rotateY(${rotateY.toFixed(1)}deg) skewY(${skewY.toFixed(1)}deg)`,
                    filter: blurPx > 0.12 ? `blur(${blurPx.toFixed(1)}px)` : 'none',
                    opacity: Number(opacity.toFixed(3)),
                    textShadow,
                  }}
                >
                  <span
                    className={`inline-block ${isFocus ? 'kinetic-focus-letter' : ''}`}
                    style={
                      isFocus
                        ? { animationDelay: `${(idx * 90) % 900}ms` }
                        : undefined
                    }
                  >
                    {char}
                  </span>
                </span>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Утончённая кинетическая полоска прогресса с бесшовным редакционным оглавлением.
 * При наведении на шкалу (или нажатии на счётчик на сенсорном экране) прямо вдоль
 * рисок плавно раскрывается полный список глав без выбивающихся карточек и наложений.
 */
export function RefinedProgressRail({
  sections,
  activeId,
  onSelect,
  smoothIndex,
  velocity,
  isNoir,
  indexOpen,
  onOpenChange,
}) {
  const [hoveredIdx, setHoveredIdx] = useState(null);
  const clampedVel = Math.max(-0.5, Math.min(0.5, velocity));
  const maxIdx = Math.max(1, sections.length - 1);
  const smoothRatio = Math.max(0, Math.min(1, smoothIndex / maxIdx));
  const activeIdx = Math.max(0, sections.findIndex((s) => s.id === activeId));

  const railShiftY = clampedVel * 16;
  const cursorStretch = 1 + Math.min(1.1, Math.abs(clampedVel) * 2.2);

  return (
    <div
      onMouseEnter={() => onOpenChange(true)}
      onMouseLeave={() => {
        onOpenChange(false);
        setHoveredIdx(null);
      }}
      className="relative z-20 flex flex-col items-start gap-4 py-3 -my-3 pr-2 will-change-transform"
      style={{
        transform: `translate3d(0, ${railShiftY.toFixed(1)}px, 0)`,
      }}
    >
      {/* Мягкая безрамочная дымка за раскрытым списком глав, чтобы текст читался чисто без «карточки» */}
      <div
        className={`pointer-events-none absolute -inset-y-6 -left-5 w-60 transition-opacity duration-300 ${
          indexOpen ? 'opacity-100' : 'opacity-0'
        }`}
        style={{
          background: isNoir
            ? 'linear-gradient(90deg, rgba(5,5,5,0.94) 0%, rgba(5,5,5,0.72) 62%, transparent 100%)'
            : 'linear-gradient(90deg, rgba(18,9,13,0.94) 0%, rgba(18,9,13,0.72) 62%, transparent 100%)',
        }}
      />

      {/* Счётчик текущей главы (также работает как переключатель оглавления на планшете) */}
      <button
        type="button"
        onClick={() => onOpenChange((v) => !v)}
        aria-expanded={indexOpen}
        aria-label="Открыть список разделов"
        className="relative z-10 flex items-center gap-2 pl-0.5 text-[10px] font-mono tracking-[0.2em] text-white/40 hover:text-white/80 transition-colors select-none"
      >
        <span className={isNoir ? 'text-white/90' : 'text-rose-400/95'}>
          0{activeIdx + 1}
        </span>
        <span
          className={`uppercase tracking-[0.22em] text-[9px] text-zinc-400 transition-all duration-300 whitespace-nowrap ${
            indexOpen ? 'opacity-90 translate-x-0' : 'opacity-0 -translate-x-2 pointer-events-none'
          }`}
        >
          Главы
        </span>
      </button>

      {/* Вертикальная ось и интерактивные строки глав */}
      <div className="relative z-10 h-[46vh] min-h-[320px] max-h-[460px] w-6">
        <div
          className={`absolute top-0 bottom-0 left-2 w-[1px] transition-colors duration-300 ${
            indexOpen
              ? 'bg-white/20'
              : isNoir
              ? 'bg-white/15'
              : 'bg-white/[0.11]'
          }`}
        />

        <div
          className={`absolute top-0 left-2 w-[1px] will-change-transform ${
            isNoir
              ? 'bg-gradient-to-b from-white/5 via-white/45 to-white/85'
              : 'bg-gradient-to-b from-rose-500/0 via-rose-500/45 to-rose-400/90'
          }`}
          style={{
            height: `${(smoothRatio * 100).toFixed(2)}%`,
          }}
        />

        <div
          className="pointer-events-none absolute left-[7px] -translate-y-1/2 will-change-transform"
          style={{
            top: `${(smoothRatio * 100).toFixed(2)}%`,
            transform: `translateY(-50%) scaleY(${cursorStretch.toFixed(2)})`,
          }}
        >
          <div
            className={`w-[3px] h-5 rounded-full ${
              isNoir
                ? 'bg-white/90 shadow-[0_0_12px_rgba(255,255,255,0.55)]'
                : 'bg-rose-400/95 shadow-[0_0_14px_rgba(225,29,72,0.7)]'
            }`}
          />
        </div>

        {sections.map((section, idx) => {
          const isActive = activeId === section.id;
          const isHovered = hoveredIdx === idx;
          const dist = Math.abs(smoothIndex - idx);
          const proximity = Math.max(0, 1 - dist * 1.25);
          const weight = 0.78 + ((idx * 29 + 13) % 100) / 140;
          const microShiftY = indexOpen ? 0 : clampedVel * weight * 16;
          const topPct = (idx / maxIdx) * 100;
          const tickWidth = isHovered ? 18 : 6 + proximity * 10;

          return (
            <button
              key={section.id}
              type="button"
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
              onClick={() => {
                onSelect(section.id);
                onOpenChange(false);
              }}
              aria-label={section.label}
              className={`group absolute left-0 -translate-y-1/2 h-9 flex items-center pl-2 z-10 text-left will-change-transform ${
                indexOpen ? 'w-52' : 'w-8'
              }`}
              style={{
                top: `${topPct.toFixed(2)}%`,
                transform: `translateY(-50%) translate3d(0, ${microShiftY.toFixed(1)}px, 0)`,
              }}
            >
              {/* Микро-риска главы */}
              <span
                className={`block shrink-0 h-[1.5px] rounded-full transition-all duration-200 ${
                  isActive || isHovered
                    ? isNoir
                      ? 'bg-white shadow-[0_0_8px_rgba(255,255,255,0.65)]'
                      : 'bg-rose-400 shadow-[0_0_10px_rgba(244,63,94,0.8)]'
                    : 'bg-white/25 group-hover:bg-white/75'
                }`}
                style={{
                  width: `${tickWidth.toFixed(1)}px`,
                  opacity: Number((isHovered ? 1 : 0.4 + proximity * 0.6).toFixed(2)),
                }}
              />

              {/* Встроенная строка названия главы (раскрывается при наведении на шкалу, без рамки и карточки) */}
              <span
                className={`ml-3.5 flex items-baseline gap-2.5 whitespace-nowrap transition-all duration-300 ${
                  indexOpen
                    ? 'opacity-100 translate-x-0 pointer-events-auto'
                    : 'opacity-0 -translate-x-2.5 pointer-events-none'
                }`}
                style={{
                  transitionDelay: indexOpen ? `${idx * 22}ms` : '0ms',
                }}
              >
                <span
                  className={`text-[10px] font-mono tabular-nums transition-colors duration-200 ${
                    isActive
                      ? isNoir
                        ? 'text-white'
                        : 'text-rose-400'
                      : isHovered
                      ? 'text-zinc-200'
                      : 'text-zinc-500'
                  }`}
                >
                  0{idx + 1}
                </span>
                <span
                  className={`text-[13px] tracking-wide transition-all duration-200 ${
                    isActive
                      ? 'text-white font-semibold'
                      : isHovered
                      ? 'text-white translate-x-1 font-medium'
                      : 'text-zinc-400/90 font-normal'
                  }`}
                >
                  {section.label}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <span className="relative z-10 pl-0.5 text-[10px] font-mono tracking-[0.2em] text-white/25 select-none">
        0{sections.length}
      </span>
    </div>
  );
}

/**
 * Левая фиксированная кинетическая панель:
 * - вертикальная шкала прогресса остаётся возле левого края экрана;
 * - крупная вертикальная типографика вычисляется и центрируется строго посередине
 *   между полоской слева и левой границей блока контента справа (симметричные отступы).
 */
export function LeftKineticNavigator({
  sections,
  playerId = 'watch-player',
  activeId,
  onSelect,
  smoothIndex,
  velocity,
  navIntro,
  playerOffsetY = 0,
  visible,
  mode = 'cinema-dof',
}) {
  const [indexOpen, setIndexOpen] = useState(false);
  const [typographyCenterX, setTypographyCenterX] = useState(124);
  const railWrapRef = useRef(null);
  const isNoir = mode === 'noir-matrix';

  useEffect(() => {
    if (!visible && indexOpen) {
      setIndexOpen(false);
    }
  }, [visible, indexOpen]);

  // Динамически измеряем положение левой шкалы и левый край контента,
  // чтобы типографика всегда находилась на равноценном расстоянии слева и справа
  useEffect(() => {
    const updateSymmetry = () => {
      try {
        const railEl = railWrapRef.current;
        const contentEl = document.getElementById(playerId);
        if (!railEl || !contentEl) return;

        const railRect = railEl.getBoundingClientRect();
        const contentRect = contentEl.getBoundingClientRect();

        // Визуальный правый край полоски (ось + активная засечка)
        const railVisualRight = railRect.left + 20;
        const contentLeft = contentRect.left;

        if (contentLeft > railVisualRight + 40) {
          setTypographyCenterX((railVisualRight + contentLeft) / 2);
        }
      } catch (err) {
        // Игнорируем промежуточные ошибки измерения при перестроении DOM
      }
    };

    updateSymmetry();
    const rafId = window.requestAnimationFrame(updateSymmetry);
    window.addEventListener('resize', updateSymmetry);

    let ro = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(updateSymmetry);
      const contentEl = document.getElementById(playerId);
      if (contentEl) ro.observe(contentEl);
      if (railWrapRef.current) ro.observe(railWrapRef.current);
    }

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener('resize', updateSymmetry);
      if (ro) ro.disconnect();
    };
  }, []);

  return (
    <div className="hidden md:block fixed inset-0 z-30 pointer-events-none">
      {/* 1. Вертикальная полоска прогресса возле левого края экрана */}
      <aside
        ref={railWrapRef}
        aria-label="Навигация по главам"
        className={`fixed left-4 lg:left-6 top-1/2 z-20 transition-opacity duration-300 will-change-transform ${
          visible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        style={{
          transform: `translate3d(${visible ? 0 : -14}px, calc(-50% + ${playerOffsetY.toFixed(1)}px), 0)`,
        }}
      >
        <RefinedProgressRail
          sections={sections}
          activeId={activeId}
          onSelect={onSelect}
          smoothIndex={smoothIndex}
          velocity={velocity}
          isNoir={isNoir}
          indexOpen={indexOpen}
          onOpenChange={setIndexOpen}
        />
      </aside>

      {/* 2. Крупная вертикальная типографика строго по центру между полоской и контентом */}
      <div
        aria-hidden="true"
        className={`fixed top-1/2 z-10 pointer-events-none transition-opacity duration-300 will-change-transform ${
          visible ? 'opacity-100' : 'opacity-0'
        }`}
        style={{
          left: `${typographyCenterX.toFixed(1)}px`,
          transform: `translate3d(calc(-50% + ${visible ? 0 : -10}px), calc(-50% + ${playerOffsetY.toFixed(1)}px), 0)`,
        }}
      >
        <div
          className={`transition-all duration-300 ease-out will-change-transform ${
            indexOpen
              ? 'opacity-10 blur-[5px] scale-[0.97]'
              : 'opacity-100 blur-0 scale-100'
          }`}
        >
          <VerticalKineticTypography
            sections={sections}
            smoothIndex={smoothIndex}
            velocity={velocity}
            navIntro={navIntro}
            mode={mode}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * Компактная мобильная пилюля-навигатор для узких экранов.
 */
export function MobileChapterPill({ sections, activeId, onSelect, visible }) {
  const [open, setOpen] = useState(false);
  const currentIdx = Math.max(0, sections.findIndex((s) => s.id === activeId));
  const current = sections[currentIdx];

  return (
    <div
      className={`md:hidden fixed bottom-[92px] inset-x-4 z-40 transition-all duration-300 ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6 pointer-events-none'
      }`}
    >
      {open && (
        <div className="mb-2 p-2 rounded-2xl bg-[#140a0e]/95 border border-white/10 backdrop-blur-xl shadow-2xl grid grid-cols-2 gap-1.5">
          {sections.map((sec, idx) => {
            const active = sec.id === activeId;
            return (
              <button
                key={sec.id}
                onClick={() => {
                  onSelect(sec.id);
                  setOpen(false);
                }}
                className={`px-3 py-2 rounded-xl text-left text-xs font-medium transition-colors ${
                  active
                    ? 'bg-rose-600 text-white'
                    : 'bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08]'
                }`}
              >
                <span className="opacity-55 mr-1.5 font-mono">0{idx + 1}</span>
                {sec.verticalLabel}
              </button>
            );
          })}
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 rounded-full bg-[#160b10]/90 border border-white/12 backdrop-blur-xl shadow-2xl flex items-center justify-between text-xs text-white"
      >
        <span className="flex items-center gap-2 font-semibold tracking-wider">
          <span className="w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_10px_#e11d48]" />
          <span className="font-mono text-rose-400">0{currentIdx + 1}</span>
          <span>{current.verticalLabel}</span>
        </span>
        <IconChevronUp
          size={16}
          className={`text-zinc-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
    </div>
  );
}

/**
 * Главный компонент приложения MediaVault.
 */
