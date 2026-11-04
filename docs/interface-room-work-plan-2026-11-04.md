# Interface, CPU backgrounds and watch rooms — 2026-11-04

- [x] Replace raster placeholders with seven small SVG media icons.
- [x] Add persistent media badges and favorites to shared cards; compact hover details.
- [x] Reuse collection sidebar anatomy for library; retain catalogue filters via a portal.
- [x] Make related-title navigation open public online identity instead of Drive matching.
- [x] Finish poster actions, seamless lower hero edge, portrait chapters, custom scrollbars.
- [x] Stabilize player settings height, icon tabs, thin accent sliders, depth controls.
- [x] Real CPU manga/illustration neural upscaling with verified persistent model/result caches and measurements.
- [x] Password watch rooms: room-scoped media access, host permissions, shared buffering, timeline sync, guest-only page.
- [x] Relevant tests and production build; deploy frontend and VM; live smoke checks.

Preserve MediaVaultPlayer as the single React player shell. Do not persist decrypted
Drive media. Room access cannot grant Drive credentials, decryption keys, arbitrary
proxy URLs, other episodes, library access or administrative rights. Caches and
all temporary/source/model artifacts stay inside this checkout's .codex-local.

## Implemented behavior and validation

Seven SVG placeholders total 2,350 bytes; the former raster placeholders no
longer enter the production bundle. Missing-card metadata enrichment is now
intersection-gated. Public catalogue favorites and collection file/group
favorites remain scoped to their respective users and views.

The optional IllustrationJaNai SPAN-S 2x worker runs on single-thread CPU/WASM.
Original artwork is immediately visible; model/result caches are independent.
Images already >=768 pixels on the long edge are left alone. Inputs are bounded
to 384 pixels on the long edge, without changing the model's learned operation.
A genuine 192x288 inference produced 384x576 in 1,130 ms in desktop Chromium;
this is an actual model measurement, not an API mock or a device-wide SLA.
The 1,673,274-byte FP32 model is SHA-256 checked before use. The browser cache
can be cleared/evicted by the browser; cookies never hold model bytes. Private
Drive artwork is excluded from the persistent output cache. The model follows
its upstream noncommercial license; see THIRD_PARTY.md and the manifest.

Rooms use the same MediaVaultPlayer React shell. Passwords are scrypt hashed;
invitation links contain room IDs, with membership tokens held in tab memory.
The server enforces leader/everyone permissions, expiry and buffering holds.
Online media, selected external audio and captions are delegated only from the
creator's existing sessions. For encrypted Drive/local files, the host browser
relays bounded decrypted Range chunks through RAM; the host must remain open.
Drive credentials/decryption keys never go to guests or the room service.
Rooms intentionally expire on server restart (no private room/media persistence).

Validation: 21 relevant Node checks; six real FastAPI/WebSocket/password/Range
contract tests using fixture media; a two-page browser test with actual MP4
playback and the real room relay; desktop/mobile hero geometry at 390, 768,
1024, 1366 and 1440 pixels (including manga poster actions on desktop).
Production build passed and includes the existing LMT integration and its source/license.

Published frontend and VM API48 at commit 0ef9292832ea0528b9c06ea2f8223493efaf6e23.
Public TLS WebSocket, scoped Range relay and installed model checksum passed;
70 existing tasks, service key and settings were preserved.
