# Manga sources and title video startup — 2026-11-04

The title showcase starts the same catalogue YouTube trailer used by card hover,
muted and without controls. In parallel, the VM resolves the exact MAL title's
non-spoiler AnimeThemes clips. It exposes the original WebM through a bounded
Range stream before downloading/transcoding the optional persistent MP4 cache.
An existing background does not change its media URL when MP4 becomes ready.
WebM decode errors keep polling for MP4; transient failures retry without a reload.
Visibility, page playback, reduced motion and manual play remain supported.

Only server-selected HTTPS v.animethemes.moe URLs can supply that stream. No
client URL, cookies, credentials, redirects or arbitrary upstream headers are
accepted. Encoders, lookups, concurrent streams, response sizes and duration are
bounded. Disk caches remain under the project's .codex-local bind mounts.

Manga Ball's extension on the VM was upgraded from 1.6.5 to 1.6.6 after backing up
its installed JAR inside the VM project's .codex-local. Trusted extension updates
now use Suwayomi's update endpoint, including successful empty responses.
Manga Ball returns the same title in languages with no chapters. Both search
paths now verify published chapter languages against its fixed public API.
A one-time SQLite migration removes only previously unverified Manga Ball search
metadata, not saved reading references, pages, other sources or account settings.
Safe source errors now reach export status, while unexpected exceptions remain
redacted. Bridge image downloads now consume the shared export byte budget.

## Verification

- 65 relevant Python tests: real queue, SQLite, HTTP Range and cleanup contracts;
  public provider/encoder responses are fixtures.
- 9 Node catalogue/title-metadata tests; production Vite/LMT builds passed.
- Chromium at 390, 768, 1024, 1366 and 1440px: real React and fixture MP4 decoding,
  progressive URL preserved after cache readiness, scrolling, pause/resume,
  player identity, reversible SVG reveal and reduced motion passed.
- Live Oracle: Manga Ball EN Lodoss has 77 chapters; first Raikou chapter has
  31 pages. The selected Suicune variant also resolves its real chapter and page
  URL. Its image CDN returns HTTP403 from Oracle; this upstream restriction is
  NOT fixed by updating the extension and is not reported as a successful export.
  RU Lodoss and JA Binzo/Magical Explorer return no matching-language chapters.
- Live Oracle: the same Lodoss work through 1Manga.co returns a valid JPEG page.
  No automatic substitution of the user's selected source or chapter is made.
- Live Oracle: exact MAL 37450 resolves 4 eligible AnimeThemes clips in 6.68s;
  the first 4KB of the selected original video arrive in 0.75s (HTTP206 WebM),
  independently of full-file download or encoding. These are separate measurements,
  not a claim that every cold title starts in under one second.

No ML inference was changed or evaluated in this update.
