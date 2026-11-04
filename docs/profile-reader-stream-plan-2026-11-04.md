# Profile, catalogue concurrency, TV and reader follow-up

Started only after the preceding frontend and VM release was verified live.

- [x] Accessible profile sections using free shadcn/ui Card / Radix Tabs patterns, AniView palette.
- [x] Scoped server-only Kodik API adapter, credential configuration, integration into discovery.
- [x] TV category and source discovery, preserving verified provider metadata.
- [x] Bounded parallel I/O on the 2-vCPU / 12-GiB Oracle VM, shared work and request priority.
- [x] Progressive title metadata and faster cached previews.
- [x] Compact reader capsules and animated mode thumbnails, all existing reading/translation options retained.
- [ ] Relevant tests/build and frontend/VM publication.

Kodik requires an owner-issued API token. None exists in the VM environment or
stored settings at the start. Google API keys cannot authorize Kodik; do not use
third-party leaked tokens or silently claim live Kodik catalogue access.

## Result and limits

The existing React player stays mounted; one API process preserves room/session
capabilities. Two import threads atomically claim distinct SQLite tasks. Eight
shared manga I/O workers use a fair queue, with at most one request per source.
Existing video discovery retains its six parallel source requests and joined
continuations. Kodik joins that same bounded batch.

Preview resolution has two slots separate from the six playback slots. Visible
chapter/video thumbnails run in two lanes, stop for playback and reuse caches.
The chapter thumbnail cache is versioned for 240x360 portraits; JPEG decoder
drafts reduce work. TVmaze episode images are keyed by season and episode.
Original media resolution is unchanged.

Core metadata appears before additional sections finish. Roles, gallery,
related works, covers and external links load together. Identical backend
requests join one future; different requests retain parallel I/O.

Four reader modes: pages, fit whole page, spread and webtoon. Animated icons
respect reduced motion. Capsules retain translation, debug and chapter controls.
Profile tabs retain account, appearance, connections and device settings.

Validation: 81 relevant Python cases with fixture upstream responses; 12 Node
cases including progressive metadata; real React browser interactions at 390
and 1440 pixels; production build. The previous release separately measured
real CPU neural inference.

Live Kodik authorization remains pending. The official kodikplayer.com landing
page requires contacting support@kodikres.com; the API returns 401 without a
token. A Gmail draft titled "Доступ к Kodik API для MediaVault" was created.
The user chose to send it themselves. No message was sent and no third-party
credential was used. The integration validates the issued key before storing
it encrypted; the token can be entered under Profile > Connections.
