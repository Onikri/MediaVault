import {useEffect, useId, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {gsap, useGSAP, reduced, PETAL, ROT} from '../motion-icons/gsap-setup.js';
import {SplitText} from 'gsap/SplitText';
import './motion.css';

gsap.registerPlugin(SplitText);
const svgId = id => 'mv' + id.replace(/[^a-zA-Z0-9_-]/g, '');

// Boot splashes: each takes `ready` (the app has its first screen) and
// `onDone` (the splash is gone). While waiting it loops; once ready it
// finishes its gesture and opens onto the site.

export function VaultMark({className = '', blossom = true}) {
  return <svg className={'vm ' + className} viewBox="0 0 192 192" aria-hidden="true">
    <circle className="vm-track" cx="96" cy="96" r="64"/>
    <circle className="vm-ring" cx="96" cy="96" r="64" transform="rotate(-90 96 96)"/>
    {blossom && <>
      <g className="vm-blossom">{ROT.map(r => <g key={r} transform={`rotate(${r} 96 96)`}><g transform="translate(96 92)"><path className="vm-petal" d={PETAL}/></g></g>)}</g>
      <circle className="vm-hub" cx="96" cy="96" r="8"/>
    </>}
  </svg>;
}

const Word = () => <div className="sp-word"><span className="sp-name">MediaVault</span><span className="sp-tag">твои истории рядом</span></div>;

function centre(root, q) {
  const box = root.getBoundingClientRect(), mark = q('.vm')[0].getBoundingClientRect();
  const cx = mark.left + mark.width / 2 - box.left, cy = mark.top + mark.height / 2 - box.top;
  return {cx, cy, unit: mark.width / 192, far: Math.hypot(Math.max(cx, box.width - cx), Math.max(cy, box.height - cy)) + 24};
}

function useExit(ready, st, exit) {
  useEffect(() => { if (ready && st.current) exit(); }, [ready]);
}

const wait = intro => Math.max(0, intro.duration() - intro.time());

/* 1. Сейф открывается — ring = progress, petals click like a combination dial,
   then the ring opens as a circular window onto the site. */
export function SplashVault({ready, onDone}) {
  const root = useRef(null), st = useRef(null), mask = svgId(useId());
  const {contextSafe} = useGSAP(() => {
    const q = gsap.utils.selector(root);
    const split = SplitText.create(q('.sp-name'), {type: 'chars', mask: 'chars'});
    const intro = gsap.timeline()
      .from(q('.sp-glow'), {opacity: 0, scale: .6, duration: 1.2, ease: 'power2.out'}, 0)
      .fromTo(q('.vm-ring'), {drawSVG: '0%'}, {drawSVG: '18%', duration: .9, ease: 'power2.out'}, .1)
      .from(q('.vm-petal'), {scale: 0, rotation: -60, transformOrigin: '50% 100%', stagger: .07, duration: .7, ease: 'back.out(2)'}, .15)
      .from(q('.vm-hub'), {scale: 0, transformOrigin: '50% 50%', duration: .4, ease: 'back.out(3)'}, .6)
      .from(split.chars, {yPercent: 110, stagger: .035, duration: .6, ease: 'power3.out'}, .35)
      .from(q('.sp-tag'), {opacity: 0, y: 8, duration: .5, ease: 'power2.out'}, .85);
    if (reduced()) { intro.progress(1); st.current = {intro, q}; return; }
    const loop = gsap.timeline({repeat: -1, delay: intro.duration() - .2})
      .to(q('.vm-blossom'), {rotation: 72, svgOrigin: '96 96', duration: .55, ease: 'back.out(3)'})
      .to(q('.sp-glow'), {scale: 1.12, opacity: .9, duration: .14, yoyo: true, repeat: 1, ease: 'power1.out'}, '<')
      .to({}, {duration: .45});
    const creep = gsap.to(q('.vm-ring'), {drawSVG: '82%', duration: 7, ease: 'power1.out', delay: intro.duration()});
    st.current = {intro, loop, creep, q};
  }, {scope: root});
  const exit = contextSafe(() => {
    const {intro, loop, creep, q} = st.current, c = centre(root.current, q);
    gsap.set(q('.sp-hole'), {attr: {cx: c.cx, cy: c.cy, r: 0}});
    gsap.timeline({delay: wait(intro), onComplete: onDone})
      .add(() => { loop?.pause(); creep?.kill(); })
      .to(q('.vm-ring'), {drawSVG: '100%', duration: .45, ease: 'power2.inOut'})
      .to(q('.vm-blossom'), {rotation: '+=144', svgOrigin: '96 96', duration: .75, ease: 'back.inOut(2)'}, '<')
      .to(q('.sp-word'), {opacity: 0, y: -12, duration: .35, ease: 'power2.in'}, '<.25')
      .addLabel('open', '-=.1')
      .to(q('.vm-petal'), {scale: 1.7, opacity: 0, transformOrigin: '50% 100%', stagger: .03, duration: .5, ease: 'power2.in'}, 'open')
      .to(q('.vm-ring, .vm-track'), {scale: 1.5, opacity: 0, transformOrigin: '50% 50%', duration: .55, ease: 'power2.in'}, 'open')
      .to(q('.vm-hub'), {scale: 0, transformOrigin: '50% 50%', duration: .3}, 'open')
      .to(q('.sp-glow'), {opacity: 0, duration: .4}, 'open')
      .fromTo(q('.sp-hole'), {attr: {r: c.unit * 58}}, {attr: {r: c.far}, duration: 1.05, ease: 'power3.inOut', immediateRender: false}, 'open+=.05');
  });
  useExit(ready, st, exit);
  return <div ref={root} className="sp" role="status" aria-label="Загружаем MediaVault">
    <svg className="sp-veil" aria-hidden="true"><defs><mask id={mask}><rect width="100%" height="100%" fill="#fff"/><circle className="sp-hole" cx="0" cy="0" r="0" fill="#000"/></mask></defs><rect className="sp-veil-fill" width="100%" height="100%" mask={`url(#${mask})`}/></svg>
    <div className="sp-center"><div className="sp-glow"/><VaultMark/><Word/></div>
  </div>;
}

/* 2. Лепестопад — petals drift in and assemble the blossom; when ready the
   blossom itself becomes a window and zooms through the screen. */
const FALLING = Array.from({length: 18}, (_, i) => ({size: 10 + (i * 7) % 16, tone: i % 3}));

export function SplashPetals({ready, onDone}) {
  const root = useRef(null), st = useRef(null), mask = svgId(useId());
  const {contextSafe} = useGSAP(() => {
    const q = gsap.utils.selector(root), box = root.current.getBoundingClientRect(), R = gsap.utils.random;
    const split = SplitText.create(q('.sp-name'), {type: 'chars'});
    const intro = gsap.timeline()
      .from(q('.vm-petal'), {x: () => R(-300, 300), y: () => R(-420, -220), rotation: () => R(-300, 300), opacity: 0, transformOrigin: '50% 100%', duration: 1.7, stagger: .13, ease: 'power3.out'}, 0)
      .fromTo(q('.vm-ring'), {drawSVG: '50% 50%'}, {drawSVG: '0% 100%', duration: 1, ease: 'power2.inOut'}, 1.2)
      .from(q('.vm-track'), {opacity: 0, duration: .8}, 1.2)
      .from(q('.vm-hub'), {scale: 0, transformOrigin: '50% 50%', duration: .45, ease: 'back.out(3)'}, 1.7)
      .from(split.chars, {y: 24, opacity: 0, rotation: () => R(-25, 25), duration: .7, stagger: {each: .04, from: 'random'}, ease: 'back.out(2)'}, 1.5)
      .from(q('.sp-tag'), {opacity: 0, duration: .6}, 2.1);
    if (reduced()) { intro.progress(1); st.current = {intro, q}; return; }
    q('.sp-fall').forEach(el => gsap.fromTo(el,
      {x: R(0, box.width), y: -40, rotation: R(0, 360)},
      {x: `+=${R(-110, 110)}`, y: box.height + 40, rotation: `+=${R(180, 540)}`, duration: R(4, 8), ease: 'none', repeat: -1, delay: R(0, 5)}));
    const breathe = gsap.to(q('.vm'), {scale: 1.04, duration: 1.3, yoyo: true, repeat: -1, ease: 'sine.inOut', delay: intro.duration()});
    st.current = {intro, breathe, q};
  }, {scope: root});
  const exit = contextSafe(() => {
    const {intro, breathe, q} = st.current, hole = q('.sp-hole-g')[0];
    breathe?.kill();
    gsap.set(q('.vm'), {scale: 1});
    const c = centre(root.current, q), p = {s: c.unit, a: 0};
    const draw = () => hole.setAttribute('transform', `translate(${c.cx} ${c.cy}) rotate(${p.a}) scale(${p.s})`);
    gsap.timeline({delay: wait(intro), onComplete: onDone})
      .to(q('.sp-word'), {opacity: 0, y: -10, duration: .35, ease: 'power2.in'})
      .to(q('.vm-ring, .vm-track'), {opacity: 0, scale: 1.3, transformOrigin: '50% 50%', duration: .4, ease: 'power2.in'}, '<')
      .add(draw, '<.25')
      .to(q('.vm-blossom, .vm-hub'), {opacity: 0, duration: .2}, '<')
      .to(p, {s: c.far / 22, a: 40, duration: 1.25, ease: 'power3.in', onUpdate: draw}, '<')
      .to(q('.sp-fall'), {opacity: 0, duration: .6}, '<');
  });
  useExit(ready, st, exit);
  return <div ref={root} className="sp" role="status" aria-label="Загружаем MediaVault">
    <svg className="sp-veil" aria-hidden="true"><defs><mask id={mask}><rect width="100%" height="100%" fill="#fff"/>
      <g className="sp-hole-g" transform="scale(0)">{ROT.map(r => <path key={r} d={PETAL} transform={`rotate(${r}) translate(0 -4)`} fill="#000"/>)}<circle r="9" fill="#000"/></g>
    </mask></defs><rect className="sp-veil-fill" width="100%" height="100%" mask={`url(#${mask})`}/></svg>
    <div className="sp-falls" aria-hidden="true">{FALLING.map((f, i) => <svg key={i} className={'sp-fall tone-' + f.tone} viewBox="-20 -44 40 48" width={f.size} height={f.size}><path d={PETAL}/></svg>)}</div>
    <div className="sp-center"><VaultMark/><Word/></div>
  </div>;
}

/* ---------- Boot splash on the site ---------- */

export const SPLASH_KEY = 'mv_boot_splash';
export const SPLASHES = [['vault', 'Сейф открывается'], ['petals', 'Лепестопад'], ['off', 'Без заставки']];
export function readSplash() {
  try { const v = localStorage.getItem(SPLASH_KEY); return SPLASHES.some(([id]) => id === v) ? v : 'vault'; } catch { return 'vault'; }
}
export function writeSplash(value) {
  try { localStorage.setItem(SPLASH_KEY, value); } catch {}
}

// The first screen is ready when the home hero shows a real release with its
// art decoded, or after a short grace on any other view. A slow release feed
// holds the splash at most three seconds; the hero has its own loading state.
function useFirstScreenReady() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const started = performance.now();
    const check = () => {
      const elapsed = performance.now() - started, hero = document.querySelector('.home-feature');
      const art = hero?.querySelector('.hero-photo img');
      const heroDone = !!hero?.querySelector('.hero-small-poster') && (!art || art.complete);
      const fonts = !document.fonts || document.fonts.status === 'loaded';
      if (elapsed > 3000 || (fonts && (heroDone || (!hero && elapsed > 900)))) { setReady(true); return true; }
      return false;
    };
    if (check()) return;
    const timer = setInterval(() => { if (check()) clearInterval(timer); }, 120);
    return () => clearInterval(timer);
  }, []);
  return ready;
}

let shownThisLoad = false;

/** The splash chosen in Оформление, over the whole page, once per page load. */
export function BootSplash() {
  const [choice] = useState(readSplash), [on, setOn] = useState(() => {
    const show = !shownThisLoad && choice !== 'off' && !reduced();
    shownThisLoad = true;
    return show;
  });
  const ready = useFirstScreenReady();
  useEffect(() => { document.documentElement.dataset.bootSplash = on ? 'on' : 'off'; }, [on]);
  if (!on) return null;
  const Splash = choice === 'petals' ? SplashPetals : SplashVault;
  return createPortal(<div className="boot-splash"><Splash ready={ready} onDone={() => setOn(false)}/></div>, document.body);
}
