import {useLayoutEffect, useRef} from 'react';
import {flushSync} from 'react-dom';
import {gsap} from 'gsap';
import {MorphSVGPlugin} from 'gsap/MorphSVGPlugin';
import {setThemeMode, useThemeMode} from '../theme-mode.js';
import {iconButton} from './NavPopover.jsx';
import './theme-toggle.css';

gsap.registerPlugin(MorphSVGPlugin);

/* Classic ⇄ Нуар. The ruby sakura spins, sheds a petal and folds into a noir
   fedora; back again the hat tips off and blooms into the flower. The page
   follows with a round wave from the button. */

const C = 12;
const PETAL = [['M', 12, 12], ['C', 9.7, 10.1, 9.1, 6.6, 10.4, 4.1], ['L', 12, 5.4], ['L', 13.6, 4.1], ['C', 14.9, 6.6, 14.3, 10.1, 12, 12], ['Z']];
const turn = (x, y, deg) => {const a = deg * Math.PI / 180, dx = x - C, dy = y - C; return [C + dx * Math.cos(a) - dy * Math.sin(a), C + dx * Math.sin(a) + dy * Math.cos(a)];};
const petalPath = deg => PETAL.map(([cmd, ...n]) => {const out = []; for (let i = 0; i < n.length; i += 2) out.push(...turn(n[i], n[i + 1], deg).map(v => v.toFixed(2))); return cmd + out.join(' ');}).join(' ');
const FLOWER = [0, 72, 144, 216, 288].map(petalPath).join(' ');
const HAT = 'M2.6 15.7C2.6 14.6 5.5 14.1 7 14.1L7.4 9.6C7.6 7.5 9.1 6.6 10.6 7.4L12 8.3L13.4 7.4C14.9 6.6 16.4 7.5 16.6 9.6L17 14.1C18.5 14.1 21.4 14.6 21.4 15.7C21.4 17 17 17.7 12 17.7C7 17.7 2.6 17 2.6 15.7Z';
const RUBY = '#f43f5e', SILK = '#f4f4f5';
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function paint(parts, noir) {
  const {shape, band, core, petal} = parts;
  gsap.killTweensOf([shape, band, core, petal]);
  gsap.set(shape, {morphSVG: noir ? HAT : FLOWER, fill: noir ? SILK : RUBY, rotation: 0, scale: 1, x: 0, y: 0, svgOrigin: '12 12'});
  gsap.set(band, {strokeDashoffset: noir ? 0 : 12, opacity: noir ? 1 : 0});
  gsap.set(core, {scale: noir ? 0 : 1, svgOrigin: '12 12'});
  gsap.set(petal, {opacity: 0});
}

// The page changes theme behind a circle growing from the button.
function switchTheme(next, button) {
  const apply = () => flushSync(() => setThemeMode(next));
  if (!document.startViewTransition || reduced()) { apply(); return; }
  const r = button.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const end = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  document.documentElement.dataset.themeWave = '';
  const wave = document.startViewTransition(apply);
  wave.ready.then(() => document.documentElement.animate(
    {clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${end}px at ${x}px ${y}px)`]},
    {duration: 760, easing: 'cubic-bezier(.22,1,.36,1)', pseudoElement: '::view-transition-new(root)'})).catch(() => {});
  wave.finished.finally(() => delete document.documentElement.dataset.themeWave);
}

export default function NavThemeToggle() {
  const noir = useThemeMode() === 'noir', button = useRef(null), refs = useRef({}), timeline = useRef(null);
  useLayoutEffect(() => {if (!timeline.current?.isActive()) paint(refs.current, noir);}, [noir]);
  useLayoutEffect(() => () => timeline.current?.kill(), []);

  function toggle() {
    const next = noir ? 'classic' : 'noir', {shape, band, core, petal} = refs.current;
    timeline.current?.kill();
    if (reduced()) {switchTheme(next, button.current); return;}
    const tl = gsap.timeline({defaults: {svgOrigin: '12 12'}, onComplete: () => paint(refs.current, next === 'noir')});
    if (next === 'noir') {
      tl.to(shape, {rotation: -144, scale: .86, duration: .38, ease: 'power2.in'}, 0)
        .to(core, {scale: 0, duration: .22, ease: 'power2.in'}, 0)
        .fromTo(petal, {opacity: 1, x: 0, y: 0, rotation: 0}, {x: 7, y: 13, rotation: 200, opacity: 0, duration: 1, ease: 'sine.out'}, .08)
        .to(shape, {morphSVG: HAT, rotation: -10, scale: 1, fill: SILK, duration: .5, ease: 'back.out(1.5)'}, .34)
        .to(band, {opacity: 1, duration: .01}, .7)
        .to(band, {strokeDashoffset: 0, duration: .3, ease: 'power2.out'}, .7)
        .to(shape, {rotation: 0, duration: .55, ease: 'elastic.out(1.1,.45)'}, .82)
        .to(shape, {y: -1.6, duration: .14, ease: 'power2.out', yoyo: true, repeat: 1}, .86);
    } else {
      tl.to(band, {strokeDashoffset: 12, duration: .16, ease: 'power2.in'}, 0)
        .set(band, {opacity: 0}, .16)
        .to(shape, {y: -3.2, rotation: -20, duration: .26, ease: 'power2.out'}, 0)
        .to(shape, {morphSVG: FLOWER, fill: RUBY, y: 0, rotation: -72, scale: .62, duration: .34, ease: 'power2.in'}, .22)
        .to(shape, {rotation: 0, scale: 1, duration: .62, ease: 'back.out(2.2)'}, .56)
        .to(core, {scale: 1, duration: .4, ease: 'back.out(3)'}, .7);
    }
    timeline.current = tl;
    switchTheme(next, button.current);
  }

  return <button ref={button} type="button" role="switch" aria-checked={noir} onClick={toggle}
    aria-label="Нуарная тема" title={noir ? 'Нуар · вернуть классику' : 'Классика · включить Нуар'}
    className={iconButton + ' kt-theme-toggle overflow-visible'}>
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" className="overflow-visible">
      <path ref={n => {refs.current.petal = n;}} d={petalPath(0)} fill={RUBY} opacity="0"/>
      <path ref={n => {refs.current.shape = n;}} d={noir ? HAT : FLOWER} fill={noir ? SILK : RUBY}/>
      <path ref={n => {refs.current.band = n;}} d="M7.25 12.5C9.6 13.15 14.4 13.15 16.75 12.5" fill="none" stroke="#0c0c0f" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="12" strokeDashoffset={noir ? 0 : 12} opacity={noir ? 1 : 0}/>
      <circle ref={n => {refs.current.core = n;}} cx="12" cy="12" r="1.7" fill="#ffe4ea"/>
    </svg>
  </button>;
}
