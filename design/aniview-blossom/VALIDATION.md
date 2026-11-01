# MediaVault Blossom integration validation

The owner-supplied AniView_Blossom_Source.zip is recorded in provenance.json.
Its design/skill/component documents are retained. Production adapters are under
src/blossom; the owner-requested graphite revision is documented in DESIGN.md.
No demo router, seeded catalog or old minified runtime was integrated.

Local validation on 2026-10-31:

- Production Vite and standalone LMT builds pass.
- 239 Node tests pass, including public metadata single-flight/cancellation,
  original Russian metadata preservation, multilingual identity/ranking,
  book/music mapping, theme persistence and contrast.
- 25 relevant Python tests pass: bounded public Jikan gateway, fallback/cache,
  concurrent requests, seasonal filtering and versioned API contracts.
- Blossom browser checks cover 360/768/1280px, actual React navigation with
  fixture responses, real image decoding, keyboard/modal search, 3:4 cards,
  all four catalog views, persistent palettes and local wallpaper.
- Title design checks cover 320/390/768/1280/1600px. Decoded video fixtures
  preserve resume/account isolation. Explicit assertions enforce 16:9 video
  and prohibit overlap between player and metadata sidebar.
- Responsive production UI, watch/voice navigation, source-only world catalog,
  source refresh, soundtrack/music navigation and playlist contracts pass.
- Immersive reader and Drive CBZ chapter handoff 20 -> 21 pass.
- A public-data browser smoke check loads live poster/thumbnail images with
  seasonal metadata at 390/1440px, without JavaScript errors or page overflow.

The deployment workflow additionally gates publication on the complete Linux
Python suite and complete browser regression suite. Some existing server/deploy
checks require POSIX file permissions/geteuid and are not portable to Windows;
these run on Linux CI, without weakening their assertions.

External API, OAuth and Drive contracts in automated suites are fixtures; video
and artwork decoding use local media fixtures. The public-image smoke check is
separate. No live Google login, physical-phone test or ML model inference is
claimed. No translator/inpaint weights, encrypted settings or server key pool
were changed. Task sources, logs, generated originals and screenshots remain
inside the project .codex-local directory.


Collection/music refinement validation:

- A catalog row with no synopsis gets an exact-ID Russian hover description;
  the measured dossier stays inside the viewport.
- Collection and online catalog reserve equal grid width, and share view-control
  geometry. Navbar center alignment is asserted for empty and playing music.
- Island geometry covers navbar contraction, phones, landscape and bottom docks.
- Browser audio tests decode/seek a real AAC fixture under the actual themed
  navbar, continue playing after collapse and release the backend lease on close.
  Provider resolution and account responses are mocks; no real OAuth or ML
  inference is claimed.

## Music catalogue recovery (2026-11-01)

The title soundtrack route now uses AnimeThemes' public GraphQL schema, preserving
exact MAL resource matching and existing AnimeThemes track IDs. MyAnimeList/Jikan
full-title credits provide a separately labelled fallback when the primary is
unavailable or has no songs. Concurrent readers share one catalogue request;
previously received public credits remain available through upstream failures.
No audio downloads, account cookies or translation keys are involved in catalogue
lookups. UI errors are recoverable, display the server detail, and identify the
actual credit provider rather than always claiming AnimeThemes.

Validation: 239 Node tests, 42 relevant Python tests, production build, soundtrack
error/retry and playlist browser contracts at 320/1280, and actual HTMLAudioElement
AAC decode/seek/lifecycle at 390/1440 with fixture resolver responses. Separately,
real Oracle diagnostics received exact-ID credits for MAL 5114 through Jikan and
the current AnimeThemes GraphQL response, and real Otonoke playback returned
HTTP 206 audio/mp4 bytes. No live Google/Spotify OAuth or ML inference was tested.

## Remembered Google grant recovery and system audit (2026-11-01)

Live Oracle refresh of the saved Google grant returned `invalid_grant`; ten ready
remembered-device records depended on that grant. This is a revoked/expired Google
grant, not a missing preference cookie. A newly authenticated user now repairs the
existing device ID via explicit Google consent instead of allocating another slot.
The server checks account ownership before issuing that consent URL. Temporary
refresh/network failures return 503 and retain local device keys; the browser retries
and recovers on focus, including after an unsuccessful initial restoration.

Validation: device-signature/replay/account-isolation/reconnect-at-limit tests;
React + real IndexedDB signing-key recovery with fixture Google and device HTTP;
239 Node tests and production build. Full Windows Python discovery ran 412 tests,
with four pre-existing POSIX permission/geteuid/open-file cleanup incompatibilities
and ten skips; Linux CI is authoritative for that suite. Live checks cover the eight
running containers, public metadata/music, authenticated Suwayomi (1633 sources)
and manga discovery (770), and translation readiness (not new neural inference or
paid Google translation). There were no recent importer tracebacks. The LLM has a
historical OOM flag but is currently running, using about 2 GiB of its 3 GiB limit.
Ten import tasks wait for Google consent; 39 are complete. Removing 22 unreferenced
old importer images and old build layers increased free disk from ~804 to ~3192 MiB;
current/rollback images, volumes, credentials, private data and models were retained.
The revoked grant still requires one interactive user consent after this release.
