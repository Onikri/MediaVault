import {useEffect, useRef, useState} from 'react';
import {jumpTitleSection, titleSectionTarget, useTitleNavigation} from '../title-navigation-store.js';
import './title-kinetics.css';

/* The kinetic chapter layer of the title page, ported from the approved
   design: big vertical letter typography between the left edge and the
   content, a refined progress rail with an inline chapter index, section
   inertia while scrolling and a background glow that morphs per chapter.
   It reads the sections TitleNavigation publishes, so it always matches the
   real page. Desktop only; tablets and phones keep the section dock. */

const VERTICAL = {titlePlayback: 'СМОТРЕТЬ', titleCharacters: 'ПЕРСОНАЖИ', titleStills: 'КАДРЫ', titleSchedule: 'РАСПИСАНИЕ', titleMusic: 'МУЗЫКА', titleRelated: 'СВЯЗИ', titleWatchOrder: 'ПОРЯДОК'};
const verticalLabel = s => s.label === 'Читать' ? 'ЧИТАТЬ' : s.label === 'В ролях' ? 'В РОЛЯХ' : VERTICAL[s.id] || s.label.split(' ')[0].toUpperCase();
// Sections whose content must never sit inside a transformed box (the player, readers).
const STILL = new Set(['titlePlayback', 'titleMaterials']);
const GLOWS = [
  ['rgba(225,29,72,.24)', 'rgba(136,19,55,.22)'], ['rgba(244,63,94,.20)', 'rgba(107,33,168,.22)'], ['rgba(190,18,60,.22)', 'rgba(59,7,100,.24)'],
  ['rgba(217,119,6,.18)', 'rgba(159,18,57,.20)'], ['rgba(168,85,247,.22)', 'rgba(225,29,72,.20)'], ['rgba(225,29,72,.20)', 'rgba(180,83,9,.18)'], ['rgba(190,24,93,.22)', 'rgba(124,45,18,.18)']
];
const desktopQuery = '(min-width: 1025px) and (prefers-reduced-motion: no-preference)';

function useDesktop() {
  const [on, setOn] = useState(() => typeof matchMedia === 'function' && matchMedia(desktopQuery).matches);
  useEffect(() => {
    const media = matchMedia(desktopQuery), change = () => setOn(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  return on;
}

/* Same physics as the design: a continuous chapter index, damped scroll
   velocity and the intro of the first chapter tied to the player's position.
   Section transforms are written straight to the DOM every frame. */
function useChapterPhysics(sections, enabled) {
  const [state, setState] = useState({smoothIndex: 0, velocity: 0, navIntro: 0, offsetY: 0, visible: false});
  const ids = sections.map(s => s.id).join('|');
  useEffect(() => {
    if (!enabled || !sections.length) return;
    let raf = 0, smooth = 0, velocity = 0, lastY = scrollY;
    const nodes = () => sections.map(s => titleSectionTarget(s.id));
    const tick = () => {
      const vh = innerHeight || 800, list = nodes(), anchor = vh * .34;
      const tops = list.map(n => n ? n.getBoundingClientRect().top : Infinity);
      let target = 0;
      if (tops[0] >= anchor) target = 0;
      else if (tops[tops.length - 1] <= anchor) target = tops.length - 1;
      else for (let i = 0; i < tops.length - 1; i++) if (tops[i] <= anchor && tops[i + 1] > anchor) { target = i + Math.min(1, (anchor - tops[i]) / Math.max(1, tops[i + 1] - tops[i])); break; }
      const delta = scrollY - lastY; lastY = scrollY;
      velocity += (Math.max(-1.35, Math.min(1.35, delta / 38)) - velocity) * .15;
      if (Math.abs(velocity) < .0006) velocity = 0;
      smooth += (target - smooth) * .17;
      // The first chapter assembles while its section rises into the working area.
      const first = list[0]?.getBoundingClientRect();
      const start = vh * .62, full = vh * .22;
      const navIntro = first ? Math.max(0, Math.min(1, (start - first.top) / (start - full))) : 1;
      const offsetY = first ? Math.max(0, Math.min(vh * .34, first.top + Math.min(first.height, vh) * .5 - vh * .5)) : 0;
      const visible = !!first && first.top < start;
      list.forEach((node, i) => {
        if (!node || STILL.has(sections[i].id)) return;
        const d = smooth - i, abs = Math.abs(d), out = Math.max(0, Math.min(1, (abs - .45) / .9)), v = Math.max(-.7, Math.min(.7, velocity));
        node.style.transform = `perspective(1350px) translate3d(0, ${(v * 36 + d * -18).toFixed(1)}px, 0) scale(${(1 - out * .045).toFixed(4)}) rotateX(${(v * 3.6 + d * 1.4).toFixed(2)}deg)`;
        node.style.filter = out * 3.4 > .12 ? `blur(${(out * 3.4).toFixed(1)}px)` : 'none';
        node.style.opacity = Math.max(.45, 1 - out * .45).toFixed(3);
      });
      setState(prev => Math.abs(prev.smoothIndex - smooth) < .001 && Math.abs(prev.velocity - velocity) < .0012 && Math.abs(prev.navIntro - navIntro) < .004 && Math.abs(prev.offsetY - offsetY) < .5 && prev.visible === visible ? prev : {smoothIndex: smooth, velocity, navIntro, offsetY, visible});
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      nodes().forEach(node => { if (node) node.style.transform = node.style.filter = node.style.opacity = ''; });
    };
  }, [ids, enabled]);
  return state;
}

function sizeClass(text) {
  return text.length >= 9 ? 'tk-letter is-long' : text.length >= 7 ? 'tk-letter is-mid' : 'tk-letter';
}

function VerticalTypography({chapters, smoothIndex, velocity, navIntro}) {
  return <div className="tk-type">
    {chapters.map((chapter, secIdx) => {
      const delta = smoothIndex - secIdx;
      if (delta < -.45 || delta > 1) return null;
      const chars = Array.from(chapter.vertical), total = chars.length;
      const introT = secIdx === 0 ? Math.max(0, 1 - navIntro) : 0, intro = secIdx === 0 && introT > .005 && delta <= .45;
      const entering = intro || delta < -.02, focus = !intro && delta >= -.02 && delta <= .58, exiting = !intro && delta > .58;
      const enterT = intro ? introT : entering ? Math.min(1, Math.abs(delta + .02) / .4) : 0;
      const hold = focus ? Math.min(1, Math.max(0, (delta + .02) / .6)) : exiting ? 1 : 0;
      const exitT = exiting ? Math.min(1, (delta - .58) / .4) : 0;
      return <div key={chapter.id} className="tk-type-layer">
        {chars.map((char, idx) => {
          const ratio = total > 1 ? idx / (total - 1) : 0, seed = (idx * 37 + secIdx * 23 + 11) % 100, weight = .72 + seed / 100 * .68;
          const depth = ((idx * 17 + secIdx * 7) % 3) - 1, v = Math.max(-.6, Math.min(.6, velocity));
          let x = 0, y = 0, z = 0, scale = 1, rx = 0, ry = 0, sk = 0, blur = 0, opacity = 1, wave = 0;
          if (entering) {
            const stagger = (1 - ratio) * .3, t = Math.max(0, Math.min(1, (enterT - stagger * .52) / (1 - stagger * .52))), e = t * t * (3 - 2 * t), w = e * weight;
            y = -w * (96 + depth * 30) - (ratio - .5) * 44 * e + v * weight * 42; x = -e * (16 - depth * 7); z = depth * e * 55;
            scale = Math.max(.74, 1 - e * .13 + depth * e * .14); rx = e * 32; ry = -e * 14; sk = -e * 3.2;
            blur = Math.min(13, w * (7.5 + Math.abs(depth) * 4.2)); opacity = Math.max(0, 1 - Math.pow(t, 1.25));
          } else if (focus) {
            wave = Math.max(0, 1 - Math.abs(hold - ratio) * 2.5); const s = wave * wave * (3 - 2 * wave);
            y = v * weight * 22; x = s * 6.5; z = s * 18; scale = 1 + s * .068; rx = v * 7; ry = s * 6; sk = v * 2.1; opacity = .87 + s * .13;
          } else {
            const stagger = ratio * .28, t = Math.max(0, Math.min(1, (exitT - stagger * .46) / (1 - stagger * .46))), e = Math.pow(t, 1.38), w = e * weight;
            y = w * (132 + depth * 42) + (ratio - .5) * 36 * e + v * weight * 88; x = -w * (14 - depth * 9); z = depth * w * 65;
            scale = Math.max(.64, 1 + depth * w * .22 - e * .11); rx = -e * 30; ry = e * 12; sk = e * 4;
            blur = Math.min(16, w * (11 + Math.abs(depth) * 4.8)); opacity = Math.max(0, 1 - Math.pow(t, 1.28));
          }
          const tone = !focus && depth === -1 ? ' is-deep' : focus && wave > .42 ? ' is-lit' : '';
          let shadow = '0 10px 28px rgba(0,0,0,.48)';
          if (focus && wave > .18) shadow = `0 0 ${(wave * 26).toFixed(0)}px rgb(var(--tk-glow) / ${(wave * .72).toFixed(2)})`;
          else if (!focus) { const shift = Math.min(7, (enterT + exitT) * 7.5); shadow = `${shift}px 0 0 rgb(var(--tk-glow) / .52), ${-shift}px 0 0 rgba(255,255,255,.22)`; }
          return <span key={idx} className={sizeClass(chapter.vertical) + tone} style={{
            transform: `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, ${z.toFixed(1)}px) scale(${scale.toFixed(3)}) rotateX(${rx.toFixed(1)}deg) rotateY(${ry.toFixed(1)}deg) skewY(${sk.toFixed(1)}deg)`,
            filter: blur > .12 ? `blur(${blur.toFixed(1)}px)` : 'none', opacity: Number(opacity.toFixed(3)), textShadow: shadow
          }}><span className={focus ? 'tk-float' : undefined} style={focus ? {animationDelay: `${(idx * 90) % 900}ms`} : undefined}>{char}</span></span>;
        })}
      </div>;
    })}
  </div>;
}

function ProgressRail({chapters, active, smoothIndex, velocity, open, setOpen}) {
  const [hovered, setHovered] = useState(null);
  const v = Math.max(-.5, Math.min(.5, velocity)), max = Math.max(1, chapters.length - 1);
  const ratio = Math.max(0, Math.min(1, smoothIndex / max)), activeIdx = Math.max(0, chapters.findIndex(c => c.id === active));
  const pad = n => String(n).padStart(2, '0');
  return <div className={'tk-rail' + (open ? ' is-open' : '')} onMouseEnter={() => setOpen(true)} onMouseLeave={() => { setOpen(false); setHovered(null); }}
    style={{transform: `translate3d(0, ${(v * 16).toFixed(1)}px, 0)`}}>
    <div className="tk-rail-haze" aria-hidden="true"/>
    <button type="button" className="tk-rail-count" onClick={() => setOpen(o => !o)} aria-expanded={open} aria-label="Открыть список разделов">
      <span className="tk-rail-current">{pad(activeIdx + 1)}</span><span className="tk-rail-word">Главы</span>
    </button>
    <div className="tk-rail-axis">
      <div className="tk-rail-line"/>
      <div className="tk-rail-fill" style={{height: (ratio * 100).toFixed(2) + '%'}}/>
      <div className="tk-rail-cursor" style={{top: (ratio * 100).toFixed(2) + '%', transform: `translateY(-50%) scaleY(${(1 + Math.min(1.1, Math.abs(v) * 2.2)).toFixed(2)})`}}><i/></div>
      {chapters.map((c, idx) => {
        const isActive = c.id === active, isHovered = hovered === idx, proximity = Math.max(0, 1 - Math.abs(smoothIndex - idx) * 1.25);
        const weight = .78 + ((idx * 29 + 13) % 100) / 140, shift = open ? 0 : v * weight * 16;
        return <button key={c.id} type="button" className={'tk-rail-item' + (isActive ? ' is-active' : '') + (isHovered ? ' is-hovered' : '')} aria-label={c.label}
          aria-current={isActive ? 'location' : undefined} onMouseEnter={() => setHovered(idx)} onMouseLeave={() => setHovered(null)}
          onClick={() => { jumpTitleSection(c.id); setOpen(false); }}
          style={{top: (idx / max * 100).toFixed(2) + '%', transform: `translateY(-50%) translate3d(0, ${shift.toFixed(1)}px, 0)`}}>
          <span className="tk-rail-tick" style={{width: (isHovered ? 18 : 6 + proximity * 10).toFixed(1) + 'px', opacity: Number((isHovered ? 1 : .4 + proximity * .6).toFixed(2))}}/>
          <span className="tk-rail-label" style={{transitionDelay: open ? idx * 22 + 'ms' : '0ms'}}>
            <span className="tk-rail-num">{pad(idx + 1)}</span><span className="tk-rail-name">{c.label}</span>
          </span>
        </button>;
      })}
    </div>
    <span className="tk-rail-total">{pad(chapters.length)}</span>
  </div>;
}

export default function TitleKinetics() {
  const nav = useTitleNavigation(), desktop = useDesktop();
  const chapters = (nav?.sections || []).map(s => ({...s, vertical: verticalLabel(s)}));
  const enabled = desktop && chapters.length > 1;
  const {smoothIndex, velocity, navIntro, offsetY, visible} = useChapterPhysics(chapters, enabled);
  const [open, setOpen] = useState(false), [centerX, setCenterX] = useState(124), rail = useRef(null);
  useEffect(() => {
    document.documentElement.toggleAttribute('data-title-kinetics', enabled);
    return () => document.documentElement.removeAttribute('data-title-kinetics');
  }, [enabled]);
  // The vertical word sits midway between the rail and the content's left edge.
  useEffect(() => {
    if (!enabled) return;
    const root = document.documentElement;
    const update = () => {
      // Content keeps a corridor of at least 232 px from the screen edge for the rail and the word.
      const sheet = document.querySelector('.title-content-sheet');
      if (sheet) root.style.setProperty('--tk-gutter', Math.max(0, Math.round(232 - sheet.getBoundingClientRect().left)) + 'px');
      const r = rail.current?.getBoundingClientRect(), content = document.querySelector('.title-content-sheet > :is(.title-stage, .mv-title-layout)');
      if (!r || !content) return;
      const right = r.left + 20, left = content.getBoundingClientRect().left;
      if (left > right + 40) setCenterX((right + left) / 2);
    };
    update();
    const observer = new ResizeObserver(update);
    const content = document.querySelector('.title-content-sheet');
    if (content) observer.observe(content);
    addEventListener('resize', update);
    return () => { observer.disconnect(); removeEventListener('resize', update); root.style.removeProperty('--tk-gutter'); };
  }, [enabled, chapters.length]);
  if (!enabled) return null;
  const activeIdx = Math.min(chapters.length - 1, Math.max(0, Math.floor(smoothIndex + .32)));
  const [glowA, glowB] = GLOWS[activeIdx % GLOWS.length], v = Math.max(-.7, Math.min(.7, velocity));
  const waveX = Math.sin(smoothIndex * 1.15) * 90, waveY = Math.cos(smoothIndex * .85) * 60;
  return <>
    <div className={'tk-glows' + (visible ? ' is-visible' : '')} aria-hidden="true">
      <i style={{backgroundColor: glowA, transform: `translate3d(${waveX.toFixed(1)}px, ${(waveY + v * 110).toFixed(1)}px, 0) scale(${(1 + Math.abs(v) * .22).toFixed(3)})`}}/>
      <i style={{backgroundColor: glowB, transform: `translate3d(${(-waveX * .85).toFixed(1)}px, ${(-waveY * .7 - v * 95).toFixed(1)}px, 0) scale(${(1 + Math.abs(v) * .18).toFixed(3)})`}}/>
      <b style={{transform: `translate3d(0, calc(-50% + ${(v * 120).toFixed(1)}px), 0) scale(${(1 + Math.abs(v) * .08).toFixed(3)})`, filter: Math.abs(v) > .05 ? `blur(${Math.min(10, Math.abs(v) * 14).toFixed(1)}px)` : 'none'}}>{String(activeIdx + 1).padStart(2, '0')}</b>
    </div>
    <div className={'tk-nav' + (visible ? ' is-visible' : '')}>
      <aside ref={rail} className="tk-rail-wrap" aria-label="Навигация по главам" style={{transform: `translate3d(${visible ? 0 : -14}px, calc(-50% + ${offsetY.toFixed(1)}px), 0)`}}>
        <ProgressRail chapters={chapters} active={nav.active} smoothIndex={smoothIndex} velocity={velocity} open={open} setOpen={setOpen}/>
      </aside>
      <div className="tk-type-wrap" aria-hidden="true" style={{left: centerX.toFixed(1) + 'px', transform: `translate3d(calc(-50% + ${visible ? 0 : -10}px), calc(-50% + ${offsetY.toFixed(1)}px), 0)`}}>
        <div className={'tk-type-dim' + (open ? ' is-dimmed' : '')}>
          <VerticalTypography chapters={chapters} smoothIndex={smoothIndex} velocity={velocity} navIntro={navIntro}/>
        </div>
      </div>
    </div>
  </>;
}
