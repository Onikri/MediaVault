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
function useKinetic(ref, enabled, apply, reset) {
  const latest = useRef(apply);
  latest.current = apply;
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (!enabled) { reset(node); return; }
    const run = p => latest.current(node, p);
    run(physics);
    listeners.add(run);
    return () => { listeners.delete(run); reset(node); };
  }, [enabled]);
}

/**
 * Обёртка кинетического раздела страницы.
 */
export function KineticSectionBlock({id, sectionIndex, enabled, isNoir, children}) {
  const section = useRef(null), line = useRef(null);
  useKinetic(section, enabled, (node, {smoothIndex, velocity}) => {
    const delta = smoothIndex - sectionIndex, absDelta = Math.abs(delta);
    const focusFactor = Math.max(0, 1 - absDelta * 1.15);
    const outOfFocus = Math.max(0, Math.min(1, (absDelta - 0.45) / 0.9));
    const clampedVel = Math.max(-0.7, Math.min(0.7, velocity));
    const translateY = clampedVel * 36 + delta * -18;
    const scale = 1 - outOfFocus * 0.045;
    const rotateX = clampedVel * 3.6 + delta * 1.4;
    const blur = outOfFocus * 3.4;
    const opacity = Math.max(0.45, 1 - outOfFocus * 0.45);
    node.style.transform = `perspective(1350px) translate3d(0, ${translateY.toFixed(1)}px, 0) scale(${scale.toFixed(4)}) rotateX(${rotateX.toFixed(2)}deg)`;
    node.style.filter = blur > 0.12 ? `blur(${blur.toFixed(1)}px)` : 'none';
    node.style.opacity = opacity.toFixed(3);
    if (line.current) {
      line.current.style.width = `${Math.round(14 + focusFactor * 86)}%`;
      line.current.style.opacity = (0.18 + focusFactor * 0.82).toFixed(2);
    }
  }, node => { node.style.transform = node.style.filter = node.style.opacity = ''; });

  return (
    <section ref={section} id={id} className="scroll-mt-24 will-change-transform relative">
      <div className="mb-6 flex items-center gap-3 overflow-hidden">
        <div
          ref={line}
          className={`h-[1px] rounded-full transition-all duration-300 ${
            isNoir
              ? 'bg-gradient-to-r from-white/75 via-white/25 to-transparent'
              : 'bg-gradient-to-r from-rose-500/80 via-rose-400/25 to-transparent'
          }`}
          style={{width: '14%', opacity: 0.18}}
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
    node.style.transform = `perspective(1000px) translate3d(${shiftX.toFixed(1)}px, ${shiftY.toFixed(1)}px, 0) scale(${scale.toFixed(4)}) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg)`;
  }, node => { node.style.transform = ''; });

  return <div ref={ref} className={`will-change-transform ${className}`}>{children}</div>;
}
