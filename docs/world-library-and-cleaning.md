# World library, temporary downloads and reader cleanup

## Navigation and discovery

`#library` is the online catalog. `#collection` contains the owner's encrypted
Google Drive library. The primary Import tab is replaced by My collection;
`#import` remains a compatible direct route. Title screens offer online playback,
save to Drive, and download to the device. Drive unlock is required only for the
Drive destination. Reconnecting Drive returns to the personal collection.

Manga discovery starts from the raw query, independently of AniList, Kitsu and
Shikimori. `/discovery/manga/sources` lists installed RU/EN/JA/KO sources;
`POST /discovery/manga/search` starts a job, and GET/DELETE of its returned ID
polls/cancels it. All routes require the owner session. Omitting `sourceIds`
selects every installed eligible source; a nonempty array restricts the search.
Explicit empty arrays and uninstalled IDs are rejected. Query script prioritizes
matching languages, without excluding other sources.

One shared four-worker queue bounds upstream concurrency. Results are cumulative;
the UI displays completed, failed and cached source counts while searches continue.
No manual windows of eight sources are needed on backend version 16. Typing a new
query cancels the previous job, including a job ID arriving after the UI unmounts.
The previous exact-title API remains compatible with older clients.

SQLite stores public title/source metadata, not manga pages. Successful query
results expire after 15 minutes; the accumulated title index expires after seven
days and is bounded to 50,000 titles. It is not a prebuilt index of every title
on every website. A cold all-source search can take minutes on an Oracle A1;
partial results appear earlier, and choosing sources narrows the work. Source
timeouts, unavailable sites, authorization and anti-bot restrictions remain visible
as failures, rather than being reported as proof a title does not exist.

Anime raw-query site results are also merged with catalog metadata. Voice
suggestions come from actually observed named Russian/unspecified-language dubs;
English voices are excluded. This is not an invented complete list of studios.
Selecting a voice automatically chooses its first available source; a disclosure
allows a manual override. Ranobe has metadata search and direct EPUB/PDF/FB2/TXT
reading; automatic ranobe site parsing is not claimed.

## Title and chapter screens

The online title view groups synopsis, facts, characters, credits, relations and
immediate reading/playback. A source-only result opens even without a catalog ID.
Available attached sources bypass a second discovery search. Exact title matches
can be inspected automatically; unrelated partial matches are not auto-opened.
Hover/focus previews use real chapter page capabilities, released on close.

`POST /online/exports` prepares a CBZ/MP4 without a Drive write. A single worker,
owner/global job limits, disk reserve, size limits, cancellation and expiry bound
temporary plaintext storage. An unguessable 15-minute capability streams the file
with range support. A completed full GET removes the temporary file; range
requests retain it for resume until expiry. Provider downloads still depend on
source availability. Browser multi-download permission can affect batch saving.

## Actual LaMa inference measured on the device

The pinned ~206 MB LaMa Manga ONNX model uses ONNX Runtime Web WASM, one CPU
thread on the current GitHub Pages origin. The NVIDIA adapter is visible to the
browser, but the graph's Fourier operations do not run through WebGPU here.
GPU availability is recorded separately from actual inference provider. This
change does not claim CUDA or GPU inference.

The former path expanded each small region into a 512×512 tensor. The new path
pads native-resolution regions to multiples of 64, between 128 and 512 pixels,
and tiles larger patches. It reuses the model session and cached verified weights.
Only validated finite output inside the dilated mask is composited; model errors
preserve the original patch. The translation render cache version is bumped.

Actual warm measurements, milliseconds, 2026-10-28, on the user's Windows device
(RTX 4080 Laptop 12 GB present; inference itself runs on CPU/WASM):

| Real manga crop | Previous 512×512 | Native ROI | Median speedup |
| --- | --- | --- | --- |
| Korean dialogue, 192×256 | 17,433 / 15,173 | 2,681 / 2,539 | 6.2× |
| Japanese vertical text, 256×512 | 13,843 / 15,970 | 7,091 / 7,372 / 6,877 | 2.1× |

The first optimized Korean call took 11,173 ms including 8,290 ms session startup.
These are two real masked crops, not full pages/chapters, OCR accuracy scores or
translation benchmarks. Private original/mask/output images and raw timing JSON
remain in `.codex-local/`; they must not be committed. Browser/provider contract
tests are separate from these actual neural runs.

Reader technical messages and retry-without-cache controls are hidden by default
behind a persisted diagnostics setting. Errors and active processing remain
visible. Wide-screen reader controls follow the configured reading width.

## Candidate models and limits

[MI-GAN](https://github.com/Picsart-AI-Research/MI-GAN) is an official mobile
inpainting implementation with ONNX export and separate MIT weight licensing.
It is a candidate for a faster neural mode; this change does not include a manga
quality/speed comparison or silently replace the existing model.
[manga-inpaint](https://github.com/syuchan1005/manga-inpaint) describes a hybrid
FP16/FP32 LaMa conversion, ~115 MB, with a WebGPU preference. Those are upstream
claims, not a verified working WebGPU path for MediaVault's current pinned model.

PP-OCRv6 Manga supplies text-line geometry, without reliable dialogue/SFX labels.
Free text in another detector is not equivalent to sound effects. No unsupported
SFX classification switch is added. Existing vision translation categories can
still guide later rendering.

## Validation

Node tests cover source-only merging, source restriction, masks/ROI geometry and
reader settings. Python tests exercise real SQLite scheduling/cache/restart,
owner isolation, temporary files/ranges/cancellation/cleanup and metadata limits,
with fixture upstream responses. Browser tests cover progressive discovery,
multi-source chips, source-only reading, destinations, responsive title/reader UI,
music controls and mocked Spotify SDK/OAuth. Production build and existing
encrypted Drive browser integration are required before release.
