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

## Next stages

- [ ] Shared selects/switches, circular icon buttons, compact player settings.
- [ ] Notification bell instead of transient global toasts.
- [ ] Persistent mounted playback session, navbar return/mini-view/history.
- [ ] Progressive manga inspection/first chapters and stream latency measurements.
- [ ] Library toolbar styling; visible showcase poster/copy parallax verification.
- [ ] Reader chapter bar/cards, cursor-driven previews, one-page/spread/3D fixes.
- [ ] Adaptive page-point timeline and compact translation settings/help.
- [ ] Language/API probe, quota/translation timings and typography/font matching.
- [ ] Actual multi-model manga/background upscale comparison with image report.
- [ ] Responsive animated calendar and watch-order presentation.
- [ ] Music rows, interval-aware OP/ED information and login diagnosis.
- [ ] Room controls, chat beside video, voice UI and two-peer checks.

Release each completed group with relevant checks and live frontend/VM validation.
Do not mark browser/media buffer retention across navigation or the unidentified
fullscreen-covering reproduction solved merely because geometry fixtures pass.
