import gsap from 'gsap';
import {useGSAP} from '@gsap/react';
import {DrawSVGPlugin} from 'gsap/DrawSVGPlugin';
import {MorphSVGPlugin} from 'gsap/MorphSVGPlugin';

gsap.registerPlugin(useGSAP, DrawSVGPlugin, MorphSVGPlugin);

export {gsap, useGSAP};

export const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

// One sakura petal: base at (0,0), notched tip 40 units up.
export const PETAL = 'M0 0C-14 -10 -18 -28 -11 -40L0 -31L11 -40C18 -28 14 -10 0 0Z';
export const SMALL_PETAL = 'M0 0C-4.5 -3 -5.5 -9 -3.5 -12.5L0 -10L3.5 -12.5C5.5 -9 4.5 -3 0 0Z';
export const ROT = [0, 72, 144, 216, 288];
