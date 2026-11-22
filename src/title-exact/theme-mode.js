import {useSyncExternalStore} from 'react';

// The site's two looks: our classic blossom and Нуар, a black dot-matrix theme.
export const THEME_MODES = [['classic', 'Классическая', 'Рубиновый свет и глубина резкости'], ['noir', 'Нуар', 'Чёрная тема в стиле dot-matrix']];
const KEY = 'mv_theme_mode';
const listeners = new Set();

export function readThemeMode() {
  try { return localStorage.getItem(KEY) === 'noir' ? 'noir' : 'classic'; } catch { return 'classic'; }
}
function apply(mode) {
  if (typeof document === 'undefined') return;
  if (mode === 'noir') document.documentElement.dataset.theme = 'noir';
  else delete document.documentElement.dataset.theme;
}
apply(readThemeMode());

export function setThemeMode(mode) {
  try { localStorage.setItem(KEY, mode); } catch {}
  apply(mode);
  listeners.forEach(fn => fn());
}
export const useThemeMode = () => useSyncExternalStore(fn => { listeners.add(fn); return () => listeners.delete(fn); }, readThemeMode, () => 'classic');

// Кинетика: inertia and morphing of the title sections while scrolling (on by default).
const KINETICS_KEY = 'mv_kinetics';
const kineticListeners = new Set();
export function readKinetics() {
  try { return localStorage.getItem(KINETICS_KEY) !== 'off'; } catch { return true; }
}
export function setKinetics(on) {
  try { localStorage.setItem(KINETICS_KEY, on ? 'on' : 'off'); } catch {}
  kineticListeners.forEach(fn => fn());
}
export const useKinetics = () => useSyncExternalStore(fn => { kineticListeners.add(fn); return () => kineticListeners.delete(fn); }, readKinetics, () => true);
