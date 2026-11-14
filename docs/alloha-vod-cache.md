# Alloha P6: pause, seeking and persistent VOD cache

The existing BNSI/native acquisition transports and validation stay in place.
Only a playback session starts continuous downloading; hover previews don't.
New devices default to the existing server-native P6 session, which keeps its
source control channel and source-provided headers. An explicitly saved BNSI
choice remains available. The direct transport can be refused during prolonged
bulk downloads; this release does not forge or replace source authentication.

* The viewer heartbeat renews both the native delivery and compatibility lease,
  including while paused. An expired bridge can be rebuilt from its still-active
  owned delivery. A lost telemetry socket alone doesn't expire HTTP media.
* Final VOD playlists are retained. Transient/nonfatal HLS failures don't rebuild
  the player. An expired control lease with playable buffered media defers recovery
  until an uncached seek or less than eight seconds of playing reserve remain.
* `DATA_DIR/.codex-local/alloha-delivery/vod` stores complete fragments, maps,
  AES-128 identity keys, manifests and subtitles. Requested quality and selected
  default audio are retained; alternative dubs/qualities aren't prefetched.
* One sequential downloader continues independently of the playhead. BNSI allows
  one concurrent foreground request so an uncached seek needn't wait behind a
  background fragment. Native browser/WS I/O keeps its original serialization.
  In-flight identical requests are joined. No video is transcoded.
  Background cache misses follow the existing importer's two-second cadence
  (`ALLOHA_PREFETCH_INTERVAL`); cache hits and foreground seeks aren't delayed.
  Expiring BNSI links renew under the same viewer capability only after release,
  dub, quality, segment layout, initialization/key hashes and the first cached
  media sample match. Renewals are bounded; changed versions never mix.
* Active viewers pin a shared variant. After the final viewer closes, files remain
  for 1,200 seconds. Capacity pressure never evicts a pinned viewer; when full,
  speculative downloading stops and normal upstream playback remains available.
  `ALLOHA_VOD_CACHE_BYTES` defaults to 60 GiB; `ALLOHA_VOD_FREE_BYTES` reserves
  8 GiB for the remaining service on the same filesystem.
* A variant key includes owner, exact source URL, referer and requested quality.
  Files have size and SHA-256 checks; incomplete downloads are not published as
  complete bundles. Changed source URLs deliberately do not alias other variants.

## Drive

When the owner has already granted offline Drive access, a complete bundle is
written to `.MediaVault playback cache` as one opaque, encrypted `.mvv` object.
The index and each fragment have independent AES-256-GCM authentication, so a
cold viewer needn't wait for an entire movie before verified playback can start.
Resumable uploads use 16 MiB chunks. One bulk archive operation runs at a time. A cache object
is indexed only after Drive confirms its byte count and MD5. The private index
is encrypted in `tasks.sqlite`; neither keys nor signed URLs enter Git.

Repeated opening first checks the local complete bundle, then the private Drive
index, then the existing upstream resolver. A cold Drive hit starts from its
private encrypted index immediately and restores the full object in the background.
Only missing foreground fragments use bounded Drive ranges (at most two); their
GCM and SHA-256 checks complete before serving. Cached seeks use VM disk only.
The bulk restore verifies the full object checksum and encrypted index too.
Archive/restore failures fall back to the existing upstream transport.

The playback archive is separate from the library catalogue and requires the
server's `service.key` and private settings backup for recovery. It is not a
new item in “Моя коллекция”. Individual bundles above 16 GiB aren't archived;
archiving also requires temporary disk space for the encrypted object.
Drive permissions, quota or insufficient disk space never interrupt playback.

## Verification

`tests/test_alloha_vod_cache.py` uses a deterministic source and fake Drive
transport for lifetime, priority, encrypted round-trip, range, integrity,
ownership, variants and partial-download tests. `tests/stream-recovery.test.mjs`
tests the control policy with media events, without launching a browser.
These are contract tests, not evidence of real CDN or Drive availability.

Real Oracle measurements, wall-clock pause and ffmpeg decoding are performed
separately over SSH. No browser or ML inference is required for these checks.
