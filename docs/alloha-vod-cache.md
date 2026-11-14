# Alloha P6: pause, seeking and persistent VOD cache

The existing BNSI/native acquisition transports and validation stay in place.
Only a playback session starts continuous downloading; hover previews don't.

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
ZIP_STORED packaging and streaming AES-256-GCM use bounded memory; resumable
uploads use 16 MiB chunks. One archive operation runs at a time. A cache object
is indexed only after Drive confirms its byte count and MD5. The private index
is encrypted in `tasks.sqlite`; neither keys nor signed URLs enter Git.

Repeated opening first checks the local complete bundle, then the private Drive
index, then the existing upstream resolver. A cold Drive hit downloads once onto
the VM, verifies SHA-256, GCM, ZIP CRCs and individual fragment hashes, and serves
all subsequent seeks locally. It doesn't issue a Drive media request per seek.
Archive/restore failures fall back to the existing upstream transport.

The playback archive is separate from the library catalogue and requires the
server's `service.key` and private settings backup for recovery. It is not a
new item in “Моя коллекция”. Individual bundles above 16 GiB aren't archived;
archiving also requires temporary disk space for plaintext ZIP and ciphertext.
Drive permissions, quota or insufficient disk space never interrupt playback.

## Verification

`tests/test_alloha_vod_cache.py` uses a deterministic source and fake Drive
transport for lifetime, priority, encrypted round-trip, range, integrity,
ownership, variants and partial-download tests. `tests/stream-recovery.test.mjs`
tests the control policy with media events, without launching a browser.
These are contract tests, not evidence of real CDN or Drive availability.

Real Oracle measurements, wall-clock pause and ffmpeg decoding are performed
separately over SSH. No browser or ML inference is required for these checks.
