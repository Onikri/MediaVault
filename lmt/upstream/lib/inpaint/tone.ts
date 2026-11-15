/**
 * MediaVault addition (2026-11): periodic-texture fill for screentone and
 * hatching, run just before Telea in the Fast ladder.
 *
 * Telea averages its neighbourhood, so a dot screen or a field of speed lines
 * comes back as a grey smear. When the known pixels of the crop repeat under a
 * small shift, a masked pixel is instead copied from the nearest known pixel
 * one or more shifts away (both directions are averaged when both exist), which
 * keeps the dots, the lines and the paper grain. Flat paper, gradients and
 * isolated edges have no such shift and are left entirely to Telea.
 *
 * Algorithmic only: no model, typed arrays, a few milliseconds per region.
 */

const MAX_SHIFT = 16;
const MIN_SHIFT = 3;
/** Texture must have at least this luma spread to be worth matching. */
const MIN_CONTRAST = 12;
/** Best shift must leave this fraction (or less) of the typical mismatch. */
const MATCH_RATIO = 0.35;
/** How far (px) a copy source may lie from the pixel it fills. */
const MAX_REACH = 64;
const MAX_SAMPLES = 2048;

export interface ToneShift {
  dx: number;
  dy: number;
  ratio: number;
}

/** Box dilation of a binary mask by `r` px: two linear passes per axis. */
function dilateMask(mask: Uint8Array, width: number, height: number, r: number): Uint8Array {
  const spread = (src: Uint8Array, dst: Uint8Array, count: number, length: number, start: (i: number) => number, step: number) => {
    for (let line = 0; line < count; line++) {
      const base = start(line);
      let since = r + 1;
      for (let k = 0; k < length; k++) {
        const i = base + k * step;
        since = src[i] ? 0 : since + 1;
        dst[i] = since <= r ? 1 : 0;
      }
      since = r + 1;
      for (let k = length - 1; k >= 0; k--) {
        const i = base + k * step;
        since = src[i] ? 0 : since + 1;
        if (since <= r) dst[i] = 1;
      }
    }
  };
  const rows = new Uint8Array(mask.length);
  const out = new Uint8Array(mask.length);
  spread(mask, rows, height, width, (y) => y * width, 1);
  spread(rows, out, width, height, (x) => x, width);
  return out;
}

/** Pixels this close to the mask carry the anti-aliased fringe of the ink and
 * are never used as evidence or as a copy source. */
const FRINGE = 2;
/** Width of the band around the mask that must itself be textured. */
const RING = 8;
/** Share of that band that must differ from its median (a balloon outline
 * crossing the band is far below this; a dot screen or hatching is above). */
const MIN_TEXTURED_SHARE = 0.1;

/**
 * The repeat vector of the texture surrounding the mask, or null.
 * Three conditions, all measured away from the ink fringe:
 *  - the band right around the mask is textured (plain balloon paper is not);
 *  - some small shift maps the known pixels onto themselves;
 *  - so does a second, non-collinear shift. A single curve such as a balloon
 *    outline or a panel border repeats only along itself and is rejected.
 */
export function findToneShift(
  data: Uint8ClampedArray,
  mask: Uint8Array,
  width: number,
  height: number,
): (ToneShift & { blocked: Uint8Array }) | null {
  const total = width * height;
  const blocked = dilateMask(mask, width, height, FRINGE);
  const near = dilateMask(mask, width, height, FRINGE + RING);
  const luma = new Float32Array(total);
  const ring: number[] = [];
  let clear = 0;
  for (let i = 0; i < total; i++) {
    const o = i * 4;
    luma[i] = 0.299 * data[o] + 0.587 * data[o + 1] + 0.114 * data[o + 2];
    if (!blocked[i]) {
      clear++;
      if (near[i]) ring.push(i);
    }
  }
  if (clear < 256 || ring.length < 64) return null;
  // Textured = differs sharply from a pixel two steps away; a smooth gradient does not.
  let textured = 0;
  for (let k = 0; k < ring.length; k++) {
    const i = ring[k];
    const x = i % width;
    const right = x + 2 < width ? luma[i + 2] : luma[i];
    const below = i + 2 * width < total ? luma[i + 2 * width] : luma[i];
    if (Math.abs(luma[i] - right) > MIN_CONTRAST || Math.abs(luma[i] - below) > MIN_CONTRAST) textured++;
  }
  if (textured / ring.length < MIN_TEXTURED_SHARE) return null;

  // Pseudo-random sample of the clear pixels (deterministic). A regular
  // lattice aliases with the screen itself and reports false repeats.
  const keep = Math.min(1, MAX_SAMPLES / clear) * 4294967296;
  const samples: number[] = [];
  let state = 0x9e3779b9;
  for (let i = 0; i < total; i++) {
    if (blocked[i]) continue;
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    if (state < keep) samples.push(i % width, (i / width) | 0);
  }

  const candidates: { dx: number; dy: number; mismatch: number }[] = [];
  for (let dy = 0; dy <= MAX_SHIFT; dy++) {
    for (let dx = dy === 0 ? MIN_SHIFT : -MAX_SHIFT; dx <= MAX_SHIFT; dx++) {
      if (dx * dx + dy * dy < MIN_SHIFT * MIN_SHIFT) continue;
      let diff = 0;
      let n = 0;
      for (let s = 0; s < samples.length; s += 2) {
        const qx = samples[s] + dx;
        const qy = samples[s + 1] + dy;
        if (qx < 0 || qx >= width || qy >= height) continue;
        const q = qy * width + qx;
        if (blocked[q]) continue;
        diff += Math.abs(luma[samples[s + 1] * width + samples[s]] - luma[q]);
        n++;
      }
      if (n >= 64) candidates.push({ dx, dy, mismatch: diff / n });
    }
  }
  if (candidates.length < 16) return null;
  const typical = candidates.map((c) => c.mismatch).sort((p, q) => p - q)[candidates.length >> 1];
  if (typical <= 0) return null;
  const limit = typical * MATCH_RATIO;
  // Shortest good shift first: closer sources, fewer seams.
  const good = candidates
    .filter((c) => c.mismatch <= limit)
    .sort((p, q) => p.dx * p.dx + p.dy * p.dy - (q.dx * q.dx + q.dy * q.dy));
  if (!good.length) return null;
  const best = good[0];
  const second = good.find(
    (c) => Math.abs(c.dx * best.dy - c.dy * best.dx) > 0.5 * Math.hypot(c.dx, c.dy) * Math.hypot(best.dx, best.dy),
  );
  if (!second) return null;
  return { dx: best.dx, dy: best.dy, ratio: best.mismatch / typical, blocked };
}

/**
 * Fills masked pixels of an RGBA buffer from their periodic twins.
 * Returns the mask of pixels it could NOT fill (for Telea), or the input mask
 * untouched when the crop is not periodic.
 */
export function periodicFill(
  imgData: ImageData,
  mask: Uint8Array,
): { remaining: Uint8Array; filled: number; shift: ToneShift | null } {
  const { width, height, data } = imgData;
  const shift = findToneShift(data, mask, width, height);
  if (!shift) return { remaining: mask, filled: 0, shift: null };

  const steps = Math.max(1, Math.floor(MAX_REACH / Math.hypot(shift.dx, shift.dy)));
  const remaining = new Uint8Array(mask);
  let filled = 0;
  const source = (x: number, y: number, sign: number): number => {
    for (let k = 1; k <= steps; k++) {
      const qx = x + sign * k * shift.dx;
      const qy = y + sign * k * shift.dy;
      if (qx < 0 || qy < 0 || qx >= width || qy >= height) return -1;
      const q = qy * width + qx;
      if (!shift.blocked[q]) return q * 4; // first clear twin
    }
    return -1;
  };
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      if (!mask[i]) continue;
      const a = source(x, y, 1);
      const b = source(x, y, -1);
      if (a < 0 && b < 0) continue;
      const o = i * 4;
      if (a >= 0 && b >= 0) {
        // Nearest twin wins outright: averaging two phases would blur the dots.
        const da = Math.abs(((a / 4) % width) - x) + Math.abs((((a / 4) / width) | 0) - y);
        const db = Math.abs(((b / 4) % width) - x) + Math.abs((((b / 4) / width) | 0) - y);
        const from = da <= db ? a : b;
        data[o] = data[from];
        data[o + 1] = data[from + 1];
        data[o + 2] = data[from + 2];
      } else {
        const from = a >= 0 ? a : b;
        data[o] = data[from];
        data[o + 1] = data[from + 1];
        data[o + 2] = data[from + 2];
      }
      data[o + 3] = 255;
      remaining[i] = 0;
      filled++;
    }
  }
  return { remaining, filled, shift };
}
