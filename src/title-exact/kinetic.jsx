import {useLayoutEffect, useRef} from 'react';

/* The reference's kinetic wrappers with the same formulas, but driven outside
   React: the page physics publish smoothIndex/velocity every frame and each
   wrapper writes its own transform to the DOM. Section contents (posters,
   cards) no longer re-render 60 times a second, which is what made scrolling
   lag once real artwork was inside. */

let physics = {smoothIndex: 0, velocity: 0};
const listeners = new Set();
export function publishPhysics(smoothIndex, velocity) {
  if (physics.smoothIndex === smoothIndex && physics.velocity === velocity) return;
  physics = {smoothIndex, velocity};
  listeners.forEach(apply => apply(physics));
}

// Subscribes `apply` (latest props via ref) while enabled; clears inline styles when disabled.
// Only wrappers near the viewport follow the physics; the rest catch up the
// moment they come close, so off-screen cards cost nothing per frame.
let watcher = null;
const nearby = new WeakMap();
function observe(node, run) {
  if (typeof IntersectionObserver !== 'function') { nearby.set(node, {near: true, run}); return () => {}; }
  watcher ||= new IntersectionObserver(entries => entries.forEach(e => {
    const entry = nearby.get(e.target); if (!entry) return;
    entry.near = e.isIntersecting;
    if (entry.near) entry.run(physics, true);
  }), {rootMargin: '60% 0px'});
  nearby.set(node, {near: true, run});
  watcher.observe(node);
  return () => { watcher.unobserve(node); nearby.delete(node); };
}
function useKinetic(ref, enabled, apply, reset) {
  const latest = useRef(apply);
  latest.current = apply;
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (!enabled) { reset(node); return; }
    const run = (p, force) => { if (force || nearby.get(node)?.near !== false) latest.current(node, p); };
    run(physics, true);
    const stop = observe(node, run);
    listeners.add(run);
    return () => { listeners.delete(run); stop(); reset(node); };
  }, [enabled]);
}

// Writes a style only when its text changes, so settled wrappers never invalidate style.
function put(node, name, value) {
  const key = '__kt_' + name;
  if (node[key] === value) return;
  node[key] = value;
  node.style[name] = value;
}
const clearPut = (node, names) => names.forEach(name => { node['__kt_' + name] = undefined; node.style[name] = ''; });

/**
 * Обёртка кинетического раздела страницы.
 */
export function KineticSectionBlock({id, sectionIndex, enabled, isNoir, children}) {
  const section = useRef(null), line = useRef(null);
  // The divider line follows focus on every section; the body moves only when enabled
  // (the player's section stays still so its media never sits in a transformed box).
  useKinetic(section, true, (node, {smoothIndex, velocity}) => {
    const delta = smoothIndex - sectionIndex, absDelta = Math.abs(delta);
    const focusFactor = Math.max(0, 1 - absDelta * 1.15);
    if (line.current) {
      // scaleX of a full-width line instead of width: no layout per frame.
      put(line.current, 'transform', `scaleX(${((14 + focusFactor * 86) / 100).toFixed(3)})`);
      put(line.current, 'opacity', (0.18 + focusFactor * 0.82).toFixed(2));
    }
    if (!enabled) return;
    const outOfFocus = Math.max(0, Math.min(1, (absDelta - 0.45) / 0.9));
    const clampedVel = Math.max(-0.7, Math.min(0.7, velocity));
    const translateY = clampedVel * 36 + delta * -18;
    const scale = 1 - outOfFocus * 0.045;
    const rotateX = clampedVel * 3.6 + delta * 1.4;
    const blur = outOfFocus * 3.4;
    const opacity = Math.max(0.45, 1 - outOfFocus * 0.45);
    put(node, 'transform', `perspective(1350px) translate3d(0, ${translateY.toFixed(1)}px, 0) scale(${scale.toFixed(4)}) rotateX(${rotateX.toFixed(2)}deg)`);
    // Blur in steps of a quarter of its range: a large section is re-rasterised
    // only when the step changes, not on every frame of the scroll.
    const step = Math.round(blur / 0.85) * 0.85;
    put(node, 'filter', step > 0.12 ? `blur(${step.toFixed(2)}px)` : 'none');
    put(node, 'opacity', opacity.toFixed(3));
  }, node => clearPut(node, ['transform', 'filter', 'opacity']));

  return (
    <section ref={section} id={id} className="scroll-mt-24 will-change-transform relative">
      <div className="mb-6 flex items-center gap-3 overflow-hidden">
        <div
          ref={line}
          className={`h-[1px] w-full rounded-full origin-left ${
            isNoir
              ? 'bg-gradient-to-r from-white/75 via-white/25 to-transparent'
              : 'bg-gradient-to-r from-rose-500/80 via-rose-400/25 to-transparent'
          }`}
          style={{transform: 'scaleX(0.14)', opacity: 0.18}}
        />
      </div>
      {children}
    </section>
  );
}

/**
 * Кинетическая карточка контента с индивидуальным весом и 3D-инерцией.
 */
export function KineticItem({weight = 1, drift = 0, sectionIndex = 0, enabled = true, className = '', children}) {
  const ref = useRef(null);
  useKinetic(ref, enabled, (node, {smoothIndex, velocity}) => {
    const clampedVel = Math.max(-0.75, Math.min(0.75, velocity));
    const delta = smoothIndex - sectionIndex;
    const outOfFocus = Math.max(0, Math.min(1, (Math.abs(delta) - 0.35) / 1.05));
    const shiftY = clampedVel * weight * 40 + delta * (weight - 1) * -22;
    const shiftX = drift * outOfFocus * 18 + clampedVel * drift * 8;
    const rotateX = clampedVel * weight * 3.2;
    const rotateY = clampedVel * drift * 1.8;
    const scale = 1 - outOfFocus * (0.02 + Math.abs(weight - 1) * 0.04);
    put(node, 'transform', `perspective(1000px) translate3d(${shiftX.toFixed(1)}px, ${shiftY.toFixed(1)}px, 0) scale(${scale.toFixed(4)}) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg)`);
  }, node => clearPut(node, ['transform']));

  return <div ref={ref} className={`will-change-transform ${className}`}>{children}</div>;
}
