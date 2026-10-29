# Moebius page mask and 3 × 3 translation — 2026-10-29

The reader sends one native-resolution page plus the union of safe glyph masks
through Moebius once. The fixed exported network receives a letterboxed 512 × 512
image and binary mask. Max pooling preserves thin strokes when reducing both the
page mask and the 64 × 64 latent mask. Only original masked pixels are composited
back. Text is typeset afterwards. Other detectors and LaMa remain available.

The runtime URL is relative to the JS module, preserving `/MediaVault/` on GitHub
Pages. An error no longer mislabels Moebius as LaMa. Missing model/runtime failures
preserve the original rather than restarting one inference for every box.

## Actual inference, separate from contract tests

RTX 4080 Laptop 12 GB, ONNX Runtime 1.26.0 CUDA EP plus CPU graph operations.
Pinned production ONNX weights, identical seed 42, guidance 3, requested steps 10
(9 denoising iterations), two warm runs per strategy in alternating order. These
are native CUDA timings, **not browser WebGPU timings or Oracle CPU timings**.
Session creation 3.661 s and first inference 1.790 s are excluded below.

| Page | Safe regions | Old region passes | One page pass | Speed ratio |
| --- | ---: | ---: | ---: | ---: |
| English page 1 | 20 | 23.939 s | 1.179 s | 20.31× |
| English page 2 | 14 | 16.811 s | 1.180 s | 14.24× |
| Japanese artwork | 6 | 6.987 s | 1.252 s | 5.58× |
| Japanese vertical | 4 | 4.730 s | 1.385 s | 3.42× |
| Korean dialogue | 2 | 2.470 s | 1.284 s | 1.92× |

All outputs changed zero pixels outside the native union mask. Korean annotations
cover two selected dialogue blocks, not every text region on that page. A fixed
512 input loses small background detail; texture seams and surviving source ink
remain visible in some regions. Neither method guarantees perfect text removal.
No quality percentage is claimed without clean ground truth. Comparison images,
full pages, mask overlays, translated examples and raw measurements stay in the
project-local `.codex-local/moebius-page-bench/` and are never published as assets.

`scripts/benchmark-moebius-native.py` verifies weight SHA-256, disables automatic
provider fallback, and records a separate optional GPU operator profile. Native
PIL resizing differs from Canvas, so these results are not pixel-identical to
WebGPU. DirectML failed during the initial UNet probe; it is not reported as a
successful benchmark. CUDA required the downloaded NVIDIA DLL directories on PATH.

## Actual Google request through Oracle HTTPS

Three annotated difficult EN/JA/KO images in one request: 4.331 s, 3665 input and
1200 output tokens, all 28 requested IDs validated. Uses the existing single
server key. A coordinate-only mixed-language probe returned all IDs but repeated
one unrelated word for the English regions; ID validation alone cannot establish
semantic quality. The report uses the later annotated request and exposes results.

The real 1.5 MB request first revealed HTTP 413: Caddy's generic 512 KB handler
also wrapped the Google route. The route is now explicitly excluded from that
handler while other request limits remain unchanged. A real repeated HTTPS
request succeeded after the fix, without restarting importer or parser services.

## Scheduling and regressions

Each key receives up to three consecutive pages. Up to three credential leases
run concurrently (nine pages). The VM worker also queues a nine-page window in
three packs. Size, 100-box client / 65-box server, token, quota, timeout and strict
UID guards remain; oversized packs split. Unknown projects share a quota budget;
keys never rotate to evade 429. Three real keys have not been benchmarked because
only one is installed. Three-pack concurrency and same-key serialization are
explicit fixtures, not live Google latency measurements.

A user-provided narrow Japanese narration box reproduced a typesetter refusal:
`сколько же прошло...` could not wrap because repeated punctuation bypassed the
word splitter. Ellipses are normalized and punctuation sequences accepted. The
original remains if fitting or masking still fails, with per-region reasons now
included in exported diagnostics.

Local Node contracts and production build pass. Python deployment tests require
Linux; Windows SQLite cleanup / `geteuid` failures are tracked separately from
actual application failures. GitHub CI runs the full Linux suite.
