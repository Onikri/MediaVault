# Reader translation update

Google requests use Oracle. Personal credentials remain in the profile's memory
or opt-in encrypted device store; server slots are encrypted with TaskStore.
Status endpoints never return credentials. Three slots can process three pages
concurrently. The sidecar splits multi-page work across configured credentials;
each result still validates every region ID before it enters the cache.

Quotas belong to Google AI Studio projects, not Google account subscriptions.
Unknown projects share the conservative existing budget. Explicit identical
project labels share a pacer. A 429 is not an immediate failover to another key.
Gemma retains its twelve-second interval. Flash-Lite allows a three-request burst
inside the same RPM/TPM/daily budget, without that Gemma-specific delay.
Existing Gemma budgets, batch/image limits and available detector choices remain.
Gemini 3.5 Flash-Lite is the default for new settings; an explicit previous model
selection is preserved. Paid Gemini is never an invisible Gemma fallback.

Deploy the importer, run `deploy/oracle/enable-reader-google.py`, and update the
batch sidecar with the pinned `install-manga-batch.py` release. The new fixed
Google route permits 20 MB; other route limits and authentication remain.
When migrating the first credential, use stdin inside the VM to encrypt it in
TaskStore; never put it in shell arguments, Git, logs or the browser response.
Two further credentials must be created by the owner and entered in the site's
protected settings. Three live keys were not available during implementation.

## Cleanup and typography

Fast cleanup derives a glyph mask. Components that continue into artwork outside
the text box are excluded. Both interior and border texture determine whether
flat fill is appropriate. Dense ambiguous SFX use neural cleanup or retain the
original; there is no whole-rectangle eraser fallback. Every model output is
composited through the original mask. LaMa, fast cleanup and all detectors remain.

Moebius is a separate Apache-2.0 model with pinned source and model revisions.
Its three ONNX artifacts total 1,241,534,740 bytes. SHA-256 is checked on download
and cache reads. WebGPU is required; unsupported devices are told to choose an
existing mode. The worker retains initialized sessions and serializes GPU work.
ONNX Runtime's asyncify artifacts are included in the production build.

Additional OFL Cyrillic fonts cover narration (PT Serif), handwritten notes
(Marck Script), system/game UI (Press Start 2P), and drawn SFX (Ruslan Display).
The prompt classifies the original glyph style separately from speech register.
Russian glyph coverage, immutable source URLs and hashes are in the manifest.

## Validation boundaries

- Node contracts include three concurrent credential leases, fixed Oracle
  transport, cache/model separation, and glyph-only preservation of crossing art.
- Python fixtures verify encrypted three-slot persistence, deletion, owner
  authentication, fixed provider destination and no immediate 429 key retry.
- Browser fixtures exercise actual detection/Canvas/cleanup/Cyrillic fonts and
  encrypted JSON cache at mobile and desktop widths. Their Russian replies are
  fixtures and do not measure Google translation quality.
- Real Moebius ONNX inference ran on NVIDIA Lovelace hardware via WebGPU, with
  pinned weights and a synthetic 256×192 patch letterboxed to 512×512, ten steps.
  Initialization: 10,891 ms; first inference: 4,355 ms; warm passes: 2,888 and
  2,850 ms. 4,492 channel values changed inside the supplied mask; zero outside.
  These are region timings, not whole-page or chapter throughput.
- Reproduce the optional neural test with `scripts/fetch-moebius-models.py` and
  `tests/moebius-real-browser.cjs`. Weights, result JSON and pictures stay in
  `.codex-local/`; they are not shipped with the source.

## Completion checks

The production importer now explicitly includes httpx and gemma-system.md. An
isolated image health check precedes replacement; installing batch dependencies
in CI no longer hides these two omissions in the production image.

Online and local chapters without Drive chunks use the same device detector and
Canvas pipeline with an authenticated Oracle credential slot. The server key is
never exported, and opening a Drive translation session is unnecessary. Browser
contracts cover this path at 390 and 1366 pixels.

Moebius uses its upstream lockfile's ONNX Runtime 1.27.0 in a separate package and
runtime directory. Detector/LaMa versions remain unchanged. The shared newer
runtime failed with GPU allocation errors in the complete reader Worker. With
the isolated runtime, actual Worker inference and Russian typesetting completed
twice: first region 16,725 ms including 11,035 ms initialization; warm region
2,548 ms inference. No artwork outside the region changed. Reproduce with
`npm run test:moebius`; this optional hardware test uses real pinned weights and
is separate from fixture Google responses.

On the updated VM, the real detector and Gemini 3.5 Flash-Lite translated a
synthetic English speech bubble: detection 679.92 ms, Google generation
3,739.17 ms, 1,752 input / 128 output tokens; the complete check took 5,093 ms.
This verifies the live provider and serialization, not multilingual quality.

After deployment, Mangago's reported chapter 4 returned twenty valid pages and a
10,547,379-byte CBZ containing twenty images with a clean ZIP CRC check. Kodik
returned its actual HLS playlist. Alloha requires the publisher Referer and an
iframe embedded at its public parent origin; the server now preserves both,
activates the public Play control and ignores Plyr's static blank.mp4. A real
selected Alloha episode returned an HLS stream, separately from eight fulfilled
server-browser contracts. No device session or Google cookies are used by these
source adapters.
