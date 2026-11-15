/**
 * Pure-JS Telea (fast-marching) inpainting.
 *
 * Replaces OpenCV.js: emscripten embind builds its JS bindings via
 * `new Function(...)`, which Chrome MV3 forbids (`'unsafe-eval'` cannot appear
 * in `content_security_policy.extension_pages`). So `cv.inpaint` could never
 * run in the offscreen document - every translate fell back to the crude
 * edge-sample blend. This module implements the same fast-marching method
 * (Telea) in plain typed-array math: no eval, no WASM, no deps.
 *
 * The core function works on an in-place ImageData + binary mask and serves as
 * the final rung of the Fast ladder (`ladder.ts`); the legacy full-frame entry
 * point was retired when the method picker collapsed to Fast vs Quality.
 *
 * MediaVault change (2026-11): the march no longer keeps a binary heap over a
 * Manhattan distance. The distance to the mask boundary is a two-pass 3-4
 * chamfer transform (near-Euclidean, so the front normal is smooth instead of
 * stair-stepped), pixels are visited in counting-sort order of that distance,
 * neighbour weights come from a precomputed table, and the weight regains
 * Telea's level-set term (neighbours at the same distance from the boundary
 * count more). Measured with scripts/benchmarks/telea-bench.mjs.
 */

const UNREACHED = 1 << 29;
const MAX_PIXELS_FRACTION = 0.8; // skip FMM if mask covers >80% of the image (degenerate)
/** Chamfer units per pixel step. */
const ORTHO = 3;
const DIAGONAL = 4;
/** Floor for the directional weight so a pixel whose known neighbours all lie
 * across the front normal is still filled instead of keeping the old ink. */
const DIRECTION_FLOOR = 0.02;

/**
 * In-place Telea fast-marching inpainting on an RGBA ImageData buffer.
 * Pixels where `mask[i] !== 0` are filled from surrounding known pixels.
 */
export function teleaInpaint(
  imgData: ImageData,
  mask: Uint8Array,
  radius = 3,
): void {
  const { width, height } = imgData;
  const data = imgData.data;
  const total = width * height;

  // Empty mask → nothing to do.
  let masked = 0;
  for (let i = 0; i < total; i++) {
    if (mask[i]) masked++;
  }
  if (masked === 0) return;
  // Degenerate safety: FMM over an almost-fully-masked image is slow and
  // pointless - the caller falls back to the edge-blend path on error.
  if (masked > total * MAX_PIXELS_FRACTION) {
    throw new Error("telea: mask covers too much of the image");
  }

  // Distance of every masked pixel to the nearest known pixel (3-4 chamfer).
  const dist = new Int32Array(total);
  for (let i = 0; i < total; i++) dist[i] = mask[i] ? UNREACHED : 0;
  for (let y = 0, i = 0; y < height; y++) {
    for (let x = 0; x < width; x++, i++) {
      let v = dist[i];
      if (v === 0) continue;
      if (x > 0 && dist[i - 1] + ORTHO < v) v = dist[i - 1] + ORTHO;
      if (y > 0) {
        const up = i - width;
        if (dist[up] + ORTHO < v) v = dist[up] + ORTHO;
        if (x > 0 && dist[up - 1] + DIAGONAL < v) v = dist[up - 1] + DIAGONAL;
        if (x < width - 1 && dist[up + 1] + DIAGONAL < v) v = dist[up + 1] + DIAGONAL;
      }
      dist[i] = v;
    }
  }
  let maxDist = 0;
  for (let y = height - 1, i = total - 1; y >= 0; y--) {
    for (let x = width - 1; x >= 0; x--, i--) {
      let v = dist[i];
      if (v === 0) continue;
      if (x < width - 1 && dist[i + 1] + ORTHO < v) v = dist[i + 1] + ORTHO;
      if (y < height - 1) {
        const down = i + width;
        if (dist[down] + ORTHO < v) v = dist[down] + ORTHO;
        if (x < width - 1 && dist[down + 1] + DIAGONAL < v) v = dist[down + 1] + DIAGONAL;
        if (x > 0 && dist[down - 1] + DIAGONAL < v) v = dist[down - 1] + DIAGONAL;
      }
      dist[i] = v;
      if (v < UNREACHED && v > maxDist) maxDist = v;
    }
  }

  // Visit order: nearest to the boundary first (counting sort, O(n)).
  const starts = new Int32Array(maxDist + 2);
  for (let i = 0; i < total; i++) {
    const v = dist[i];
    if (v > 0 && v < UNREACHED) starts[v + 1]++;
  }
  for (let v = 1; v < starts.length; v++) starts[v] += starts[v - 1];
  const order = new Int32Array(starts[maxDist + 1]);
  for (let i = 0; i < total; i++) {
    const v = dist[i];
    if (v > 0 && v < UNREACHED) order[starts[v]++] = i;
  }

  // Neighbour table: offsets and the distance weight 1 / (1 + |p−q|²).
  const side = 2 * radius + 1;
  const tableDx = new Int8Array(side * side - 1);
  const tableDy = new Int8Array(side * side - 1);
  const tableInvLen = new Float32Array(side * side - 1);
  const tableDst = new Float32Array(side * side - 1);
  let entries = 0;
  for (let dy = -radius; dy <= radius; dy++) {
    for (let dx = -radius; dx <= radius; dx++) {
      if (dx === 0 && dy === 0) continue;
      const distSq = dx * dx + dy * dy;
      tableDx[entries] = dx;
      tableDy[entries] = dy;
      tableInvLen[entries] = 1 / Math.sqrt(distSq);
      tableDst[entries] = 1 / (1 + distSq);
      entries++;
    }
  }

  const known = new Uint8Array(total);
  for (let i = 0; i < total; i++) known[i] = mask[i] ? 0 : 1;

  for (let n = 0; n < order.length; n++) {
    const idx = order[n];
    const x = idx % width;
    const y = (idx / width) | 0;
    const here = dist[idx];

    // Front normal = gradient of the distance field.
    const xL = x > 0 ? dist[idx - 1] : here;
    const xR = x < width - 1 ? dist[idx + 1] : here;
    const yU = y > 0 ? dist[idx - width] : here;
    const yD = y < height - 1 ? dist[idx + width] : here;
    let gx = xR >= UNREACHED || xL >= UNREACHED ? 0 : xR - xL;
    let gy = yD >= UNREACHED || yU >= UNREACHED ? 0 : yD - yU;
    const gnorm = Math.hypot(gx, gy);
    const flat = gnorm < 1e-6;
    if (!flat) {
      gx /= gnorm;
      gy /= gnorm;
    }

    // Telea colour estimate: weighted average of known neighbours.
    // weight = dirWeight² · dstWeight · levWeight
    //   dirWeight = |N(p)·(p−q)| / |p−q|     (along the front normal)
    //   dstWeight = 1 / (1 + |p−q|²)
    //   levWeight = 1 / (1 + |T(p)−T(q)|)    (same distance from the boundary)
    let r = 0;
    let g = 0;
    let b = 0;
    let sumW = 0;
    for (let k = 0; k < entries; k++) {
      const qx = x + tableDx[k];
      const qy = y + tableDy[k];
      if (qx < 0 || qy < 0 || qx >= width || qy >= height) continue;
      const q = qy * width + qx;
      if (!known[q]) continue;
      const dir = flat ? 1 : Math.abs(tableDx[k] * gx + tableDy[k] * gy) * tableInvLen[k];
      const level = 1 / (1 + Math.abs(here - dist[q]) / ORTHO);
      const weight = (dir * dir + DIRECTION_FLOOR) * tableDst[k] * level;
      const o = q * 4;
      r += data[o] * weight;
      g += data[o + 1] * weight;
      b += data[o + 2] * weight;
      sumW += weight;
    }

    if (sumW > 0) {
      const out = idx * 4;
      data[out] = r / sumW;
      data[out + 1] = g / sumW;
      data[out + 2] = b / sumW;
      data[out + 3] = 255;
    }
    known[idx] = 1;
  }
}
