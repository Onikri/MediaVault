# Follow-up review: execution stages

The detailed requirements are recorded in the 23-section review plan in the task
conversation. Preserve existing functionality and the supplied AniView design.
All caches, logs, browser profiles and temporary/model files stay in project
`.codex-local`. Do not introduce adult video catalogue integrations.

## Stage 1 — playback recovery, queue and background refresh

Implemented:

- A playback-health timeout is recoverable local state, not a fatal resolver
  failure. Playing/progress clears it. The compact status can be dismissed.
- Actual playing clears stale parent errors for both online and Drive viewers.
  Online errors have a dismiss action. Auxiliary audio/preview videos have an
  explicit hidden DOM state and display:none, independent of stylesheet order.
- Background catalogue refresh is silent, singleflight, and cannot overwrite
  a concurrent foreground write/unlock. It does not toggle global busy or toast.
  The blanket prohibition on choosing local files during server work is removed;
  existing merge/conditional-write safeguards remain in place.
- Identical active enrichment submissions reuse one job. At startup, legacy
  identical queued/recovered jobs merge into the earliest cursor. All historical
  records/results remain; merged duplicates release their redundant task keys.
  Owner, library, target and key scope must match. Imports run ahead of queued
  background decoration. Active jobs cannot disappear behind the history limit.
- Enrichment progress exposes title/file/current operation: catalogue, metadata,
  video probing, frame extraction, preview upload, image download, profile save.
  The queue provides list/cards/table, sorting, filters, grouping and persistent
  presentation preferences. Merged duplicates remain available via history filter.
- Provider-updated YouTube cookies are retained in the encrypted store only if
  the same jar is still current. A late diagnostic from an older session cannot
  reject a freshly uploaded jar. No automatic OAuth-to-stream access is claimed.

Checked: 38 focused Python contracts (including real local frame extraction),
17 Node upload/import/player checks, and React browser contracts at 390/1440px.
The browser uses real MP4 decoding for timeline previews, while stall events and
queue/provider responses are controlled fixtures. Production build passed.
These are not a real YouTube playback or new ML benchmark result.

## Stage 2 — shared controls and notifications

- Added pinned MIT Radix Select/Switch primitives with existing AniView tokens.
  Player settings, season selection and queue controls share the same select.
  Lists stay in the player in fullscreen; settings switches retain real player
  preference updates. Remaining reader/catalogue controls will migrate later.
- Player settings use one compact column, a narrower panel and stable tab height.
  Profile/notification icon buttons keep equal dimensions on mobile and desktop.
- Notifications collect behind the navbar bell instead of global toast overlays.
  Records are account-scoped, bounded to 100, persisted in browser storage, and
  repeated messages are grouped. Read/all-read/clear actions are provided.
- Task transitions create notifications with a queue action. Last-seen job states
  survive reopening the browser so newly completed background work can surface.
  Existing history is not flooded into notifications on first activation.
- Focused browser checks cover season/speed selection, switches, stable settings
  height, retained media element, actual navbar with music, notification persistence,
  and select portals within real fullscreen at 390/1440px. Existing React player
  identity/theater/extension lifecycle checks and production build passed.

## Stage 3 — retained media and progressive chapters

- A workspace-level React host keeps the opened inline video/reader owner mounted
  across page navigation. It pauses on leaving, retains the media element/buffer,
  supports a navbar return action, mini view and explicit close. Only one session
  stays active; logout/library lock removes its in-memory capabilities.
- Recent-view history is account scoped and contains public labels/routes only.
  Signed URLs, React props, decrypted pages and thumbnail frames are not persisted.
  Returning scrolls to the player. Local episode selection has its own retained
  state; the SVG reveal remains inside the live player tree.
- Chapter metadata is published before the separate real-image check completes.
  Automatic selection reuses that metadata instead of parsing the title again.
  Reading/export remain gated on actual source readability; failed sources retain
  chapter navigation and explicit retry. Source checks stop while reading/hidden.
- The bounded server metadata cache returns isolated copies, so request-specific
  readability flags cannot contaminate later metadata. Explicit retries refresh
  metadata, while subsequent verification reuses the same parsed chapter list.

Validation: 9 Python inspection/readability contracts, scoped-history Node test,
real React progressive-provider checks at 390/1440px and source-health checks at
360/1440px. Real local MP4 decoding confirms identical video DOM, retained buffer,
position and no metadata reload after page unmount/mini-view/return. Existing
React player identity/theater/extension checks passed. Provider replies in manga
browser checks are fixtures; this is not a live-source latency guarantee or a
YouTube playback result. Standalone non-inline local readers are not retained.

## Stage 4 — library surfaces, showcase layers and chapter navigation

- Catalogue actions now use individual collection-style icon/label surfaces.
  Search uses the same quiet material, without adding collection-only actions.
- The poster, copy and facts have distinct reversible scroll velocities; the
  poster scales subtly while the video moves behind it. Production geometry
  remains checked from phone width through ultrawide screens.
- Reader volume/chapter controls sit beside the title and share the Radix list
  component. Repeated direction/chapter subtitles are removed. Chapter contents
  use vertical mini cards, with available artwork and current-chapter indication.
- A reusable chapter scrub preview follows pointer position across 5 or 8 sampled
  pages, depending on connection quality. Save-data disables automatic preview.
  Online preview preparation is delayed on hover and its lease is released on exit.
  Local archive previews decode only selected samples into small RAM thumbnails.
  Decorative overlays no longer intercept pointer movement; wrapped chapter cards
  now fill their grid column instead of shrinking to the caption width.
- The real StPageFlip book uses measured fixed page dimensions: one-page mode is
  truly portrait, spreads use two pages. Its wrapper has real height, and custom
  React turns are no longer blocked by the library's native-click corner filter.
  RTL/LTR turns are covered. Existing render-loop cancellation was verified; the
  remaining resize listener is now removed when native mouse gestures are off.

Validation: real browser pointer/image decoding and 5/8-page budgets, real engine
portrait/spread and forward/backward sheet animation at 390/1440px; one renderer
frame while mounted and none after closing. Profile/reader checks, chapter
thumbnail concurrency/persistence, nested library layout, reversible showcase
layer velocities, SVG reveal/media continuity and built first-screen geometry
passed. Production build passed. Provider/artwork data are controlled fixtures;
these checks do not claim new ML inference or live YouTube availability.

## Stage 5 — page track and translation settings

- Reader navigation is a thin sampled point track. Its spring indicator follows
  the current page/range, points enlarge near the cursor and show a page label.
  Point count adapts to available length, capped at 120 for long chapters.
- Pointer seeking uses the exact cursor position, with keyboard range controls
  retained. Previous/next sit at the track ends; all-page previews moved to the
  upper toolbar. Webtoon keeps a vertical right-side track and compact counter.
- Translation settings use the full panel width, category headings and aligned
  controls. Help is a circular question button instead of a full-width action.
  Personal keys remain available in a collapsible connection section.
- The two principal payload choices use existing Lucide icons, hover explanations
  and a selected-mode description. All four prior payload modes remain available
  in the additional markup section; no translation capability was removed.
- Translation lists/switches use shared Radix controls. Select portals now respect
  their surrounding dialog, fixing options appearing behind the reader panel.

Validation: page-position/point bounds Node checks, real React pointer dragging,
keyboard seeking, horizontal/vertical layout, top previews, help and all payload
choices at 390/1440px. Existing profile/reader checks passed. API/provider replies
in the UI checks are fixtures; this stage does not benchmark translation or ML.
Production build passed.

## Stage 6 — language/key probe and typography

- Explicit translation start can check the dialogue language using two reduced
  pages and the selected personal/server credential mode. SFX proportions are
  separate; ambiguous/unsupported text keeps the user's language. Manual language
  selection disables automatic detection. No probe runs just by opening a reader.
- Probe is quota paced, cancellable, has a 15-second deadline and no retry storm.
  Its result is reused in the open chapter; credentials/model changes invalidate
  the result. Errors do not launch translation silently. Missing credentials can
  still leave existing translated cache readable.
- Real Oracle/API measurements are in google-translation-diagnostics-2026-11-05.md.
  The final production language prompt/schema returned valid English percentages
  in 3.487 s; small two-page translations took 1.412–6.243 s, or 8.966 s including
  provider cooldown/rerouting. One trial received HTTP 503. This is not a dense
  full-chapter end-to-end guarantee.
- Added licensed local Cyrillic Balsamiq Sans regular/bold and Caveat. Ordinary
  dialogue stays Comic Relief; strong rounded shouts/loose notes gain distinct
  fonts. The renderer image cache version changed, keeping translated JSON reusable.
  Translation button shows active preparation instead of a frozen icon.

Validation: 14 Node translation/language checks; real canvas JPEG reduction and
FontFace decoding; actual reader start/detection/cleanup/Cyrillic worker with
fixture Google replies at 390/1440px. Full direct-translation browser contract
passed at 390/1366px (real contour detector, worker rendering, encrypted cache,
lettering changes and quota diagnostics; no real Google in that browser test).
Live Google API requests are separately documented, with no keys printed.
Production build passed.

## Stage 7 — measured CPU upscale profiles and release calendar

- Added real SPAN detail/denoise and FSRCNN CPU profiles, model choice in reader
  settings, per-profile SHA-256 verification/cache identity and bounded inference.
  The worker handles real RGB or luminance networks, keeping original chroma for
  FSRCNN. Too-large originals are kept instead of labelled as an enhancement.
- New weights stay in project cache and are served through explicit hash-checked
  model routes. Reproduction supports --profile detail/denoise/fast. Manifests and
  attribution distinguish IllustrationJaNai from grayscale MangaJaNai ESRGAN.
- The image/timing comparison is docs/upscale-comparison-2026-11-05.md. Actual
  native CPU inference on 192×256 samples took about 453–484 ms SPAN or 25–35 ms
  FSRCNN, with controlled reconstruction metrics and separate reference/baseline
  images. Browser CPU/WASM ran all three actual models, not mock inference.
- Replaced handwritten month geometry with MIT React DayPicker 10.0.2. Calendar
  is one or two months according to its actual width, with animated navigation,
  Russian shared month/year dropdowns and season shortcuts. Dates are circular.
  Episode details open on hover/focus and close when leaving; touch can tap.
  The compact list still includes every episode with available name/filler/credits.

Validation: actual hash-verified ONNX CPU/WASM inference; independent native CPU
comparison images; Python route/hash safety contracts; real DayPicker/Radix
navigation, 64 entries, one/two-month responsiveness and hover dismissal at
390/1440px. Calendar episode replies are fixtures, not live schedule guarantees.
Production build passed. Watch-order visual refinement remains a separate item.

## Stage 8 — watch routes and compact soundtrack rows

- Watch order distinguishes catalogue prequel/sequel continuity from all works in
  release order. It does not present release dates as an authoritative Fate route.
  Shared Radix selector, numbered connected rows and current-title marker replace
  the native dropdown. Expansion keeps numbering correct and exposes every work.
- Soundtrack rows use one play surface, compact title/type/artist/episode text and
  round info/save/more actions. Information expands in the existing row with Motion;
  compact player lists retain their separate song sheet and playlist functions.
  The anime poster is no longer repeated as an alleged cover for every recording;
  actual supplied recording covers are preserved, with an icon when none is supplied.
- OP/ED credits use the title area below the episode controls. The floating overlay
  that covered season/episode selection is removed. Only an unambiguous matching song
  is shown. Episode ranges accept en/em dash and spaces as well as ASCII hyphens.
- Calendar arrow targets now also explicitly retain equal width and height against
  legacy global button minimums.

Validation: 10 focused Node player/franchise checks; real React/Radix/Motion route
switching/numbering/navigation, inline song detail expansion, circular actions and
actual media-time cue layout at 390/1440px. Catalogue/timing responses are fixtures;
this pair does not claim new real YouTube playback. Production build passed.

## Next stages

- [x] Shared selects/switches, circular navbar icon buttons, compact player settings.
- [x] Notification bell instead of transient global toasts.
- [x] Persistent mounted playback session, navbar return/mini-view/history.
- [x] Progressive manga inspection/first chapters (provider timing fixtures).
- [ ] Live stream/source latency measurements across providers.
- [x] Library toolbar styling; visible showcase poster/copy parallax verification.
- [x] Reader chapter bar/cards, cursor-driven previews, one-page/spread/3D fixes.
- [x] Adaptive page-point timeline and compact translation settings/help.
- [x] Language/API probe, quota/translation timings and typography/font matching.
- [x] Actual multi-model manga/background upscale comparison with image report.
- [x] Responsive animated calendar.
- [x] Watch-order presentation.
- [x] Music rows and interval-aware OP/ED information.
- [ ] YouTube/session/login investigation (last).
- [ ] Room controls, chat beside video, voice UI and two-peer checks.

Release each completed group with relevant checks and live frontend/VM validation.
Do not mark browser/media buffer retention across navigation or the unidentified
fullscreen-covering reproduction solved merely because geometry fixtures pass.
