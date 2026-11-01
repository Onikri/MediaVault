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
