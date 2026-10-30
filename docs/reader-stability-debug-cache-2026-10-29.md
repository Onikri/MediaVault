# Reader stability and local model storage

The supplied 3.2-second recording shows a blank scroll surface and page-number
oscillation while cleanup is running. Previously every visibility observer
change disposed the image URL and restarted translation. Pages now keep a
stable resource, delay offscreen eviction, preserve their measured geometry,
and do not cancel rendering merely because the observer changes.

As of October 30, both manga and webtoon/manhwa use each source image's
intrinsic width, shrinking to the viewport without upscaling. See
[the blocks update](reader-blocks-2026-10-30.md) for the current behaviour.

The warning-outline button beside translation opens a nonmodal debug panel:

- Actual detector boxes and their IDs, before Google geometry changes.
- Optional cleanup snapshot before any Russian lettering, captured in memory.
- Existing request preview, sent images, response and measured timings.
- Queue states and numbered credential slots, without credential values.
- Configured server hostname and an IP only when encoded in that address.
  Public egress IP is explicitly unmeasured.

Debug reconstruction reuses stored translation JSON when available. It may
rerun detection/cleanup, but does not request Google just to reproduce request
diagnostics. Historical request bodies are not reconstructed from guesses.
Intermediate cleanup images are not written to the translation cache.

Model files already use CacheStorage. Users can additionally select a directory
through the File System Access API; its handle lives in IndexedDB, not cookies.
No arbitrary path is readable without user-granted permission. Revoked access
can be restored through the settings button. No filesystem access prompt runs
inside a worker. Directory files are keyed by full source URL/revision and
checked against the existing SHA-256 manifests before use.

Preloading covers the chosen detector and inpaint model in Google modes.
The October 30 update adds OCR and GGUF packs for local Hy-MT2 and Index;
experimental WebLLM retains its own browser cache. Moebius and the upstream
LMT downloader read the directory cache. Incomplete streamed downloads are
rejected. Download percentages represent observed byte counts and known sizes.

One idle canvas worker is retained for two minutes to reuse loaded sessions
between readers. A busy renderer is terminated on close. The idle renderer
is also released when the page is hidden/unloaded.

## Validation

Node regression tests exercise URL lifetime and asynchronous close races,
directory-handle persistence contracts and revocation, byte progress, redaction,
worker reuse, and reuse of translation JSON during debug reconstruction.
Canvas tests verify snapshot ordering with a fixture provider. These are
contract tests, not new neural inference or WebGPU performance measurements.

The production build includes both the website and the attributed AGPL LMT.
Local Python catalogue tests pass. A Windows batch test encounters the existing
open-SQLite-file cleanup failure; Linux CI is the release gate.

No provider safety-filter bypass or automatic pornographic archive downloader
is introduced.
