# MediaVault Blossom integration validation

The UI uses the owner-supplied archive recorded in provenance.json. The design
documents and original reference CSS are retained here; editable production
adapters are under src/blossom. No demo router, seeded AniView catalog or old
minified runtime was integrated.

Local validation on 2026-10-31:

- Production Vite build and standalone LMT build pass.
- 232 Node tests pass, including palette persistence input validation, accessible
  derived colors, neutral backgrounds and private files without metadata.
- 41 relevant Python tests pass: anime browse/biography, title ratings/extras,
  player contracts, online playback and AniSkip.
- Blossom browser tests cover 360/768/1280px, real React navigation with fixture
  catalog responses, keyboard search, exact 3:4 cards, palette selection and
  reload, local IndexedDB wallpaper and background/manual mode switching.
- Production UI tests cover 320/390/768/1280px, filters, autocomplete, IME,
  partial results, retry, profile and responsive navigation.
- Vault browser regression covers mocked Google OAuth/Drive, actual encryption,
  private file upload, favorites/history, account isolation, device persistence,
  virtual WebAuthn, playback/seek and durable resume.
- Title design, watch, world catalog, music navigation and immersive reader
  suites pass, including actual browser decode of local video/audio fixtures and
  Drive CBZ chapter handoff 20 → 21.

External API/browser contract responses are fixtures. This validation does not
claim a live Google login, a new external-source availability survey, physical
phone testing or ML model inference. No translator/inpaint model or server key
pool was changed by this interface update. Private screenshots and test logs
remain in .codex-local and are not part of the published repository.
