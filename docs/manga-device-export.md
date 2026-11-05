# Manga export to a device

The title's **Save to device** form supports original pages, translation using
Google credentials held on Oracle, and fully rendered chapters from the reader's
encrypted browser cache. CBZ is the default; ZIP contains the same image bytes.
PDF embeds pages as high-quality JPEGs and can therefore change fine image detail.
Selection accepts chapters (including fractional extras), a list of volume ranges,
one file per chapter, one per volume, or one file containing the selection.

The reader's download icon exports the current translated chapter directly.
For a chapter opened from Drive without a public source URL, complete its
translation in the reader first. A partial chapter is never labelled complete.

## Processing and privacy

The authenticated browser submits page hashes, uploads available translated
images to a staged owner-scoped export, then commits it to the bounded export
queue. Each upload is matched against its SHA-256 manifest, verified as an image,
and limited to 30 MB / 24 MP. There is no arbitrary input path or browser script.
Cached source hashes are compared with originals for partial chapters. Fully
cached chapters do not fetch originals or make translation requests.

Missing pages use the existing reader's `DirectChapter`, Google request builder,
cleanup worker and Cyrillic renderer, executed in a headless Chromium process
on Oracle. Server keys never reach that browser: a fixed binding forwards requests
to the existing local Google gateway, sharing its per-key concurrency and quotas.
Packets contain two or three pages, up to three keys in parallel. Cancellation
and the export time/byte budgets also apply to rendering. Heavy model weights,
if selected, are downloaded from the same restricted model hosts as the reader.

Completed VM translations are cached encrypted with the existing service key
and an owner/source/settings/version identity (7 days, 512 MB). Browser cache
stays encrypted too. Temporary plaintext export files live only in the project's
data directory and are removed on complete download, cancellation, failure,
expiry or restart. Device downloads are plaintext CBZ/ZIP/PDF. The existing
Drive import route is unchanged and continues encrypting its files.

Limits: 100 chapters and 1500 pages per file, existing 1 GB export budget and
30-minute deadline. A busy/slow model or provider quota can require a smaller
selection. Failed exports preserve successfully rendered encrypted VM cache pages.

## Installation

Requires API version 50. Build with `npm run build`; serve that exact `dist/`
tree privately inside the importer at `/app/export-assets` (or set
`MANGA_EXPORT_ASSETS`). This includes `manga-export.html`, hashed JS/workers,
`reader-fonts/`, and the attributed AGPL LMT build under `lmt/`. It is separate
from the public main page. Keep Playwright profiles/model caches under the
mounted project's `DATA_DIR/.codex-local/`. Apply the Caddy upload size route in
`deploy/oracle/Caddyfile` together with the API update. Publish corresponding
integration source with the existing LMT attribution and licenses.

## Validation

- Node tests: grouping, range selection, preservation of fractional chapters,
  translator settings without keys, existing translation/direct-reader contracts.
- Python tests: real ZIP/CBZ/PDF bytes, ownership, staging, hash checks, cancellation,
  incomplete cache rejection, and encrypted VM cache reuse. Provider translation
  is explicitly mocked in these archive/queue tests.
- Browser contract: real React controls, IndexedDB AES-GCM cache and binary upload;
  API replies are fixtures. It does not claim an ML inference quality check.
- Actual provider/inpainting execution is checked separately on the VM; see the
  release validation report for the actual model and outcome.
