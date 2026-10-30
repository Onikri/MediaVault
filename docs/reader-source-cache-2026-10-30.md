# Online manga image recovery, 2026-10-30

RawINU and WeLoveManga could list `ATM Ojisan: Isekai de Moteki ga Tomaranai!`
chapter 2, but every page returned HTTP 500 from private Suwayomi with
`No space left on device`. The host still had 3.6 GiB free. The full filesystem
was the 64 MiB executable JNI tmpfs: `java.io.tmpdir` also determines Suwayomi's
`Tachidesk/manga-cache` location. This was a server storage failure before any
translation, unrelated to online-session expiry.

The native runtime repair now mounts only the `Tachidesk` subtree onto
`/opt/mediavault-suwayomi/.codex-local/cache/suwayomi-reader`. The existing pinned
official image, private network, native-library loading and account configuration
are retained. Native extraction uses 600 KiB in the separate executable tmpfs.

`mediavault-source-cache.timer` checks the disposable disk cache every two minutes.
It expires files after one hour and removes oldest eligible files above 512 MiB.
Files modified in the last five minutes are protected, so the size target can be
temporarily exceeded during active downloads. Only the dedicated cache is pruned;
saved downloads, extensions, credentials and model weights are outside its scope.
Operational scripts, logs and rollback backups are under `.codex-local`.
Run `enable-suwayomi-native.py` with its sibling `prune-suwayomi-cache.py` present
to reproduce the integration on the existing VM.

The source adapter now classifies storage exhaustion without exposing upstream
response contents. The reader displays bounded JSON source errors and distinguishes
them from HTTP 410 session expiry.

## Verification

- Real production public API: chapter preparation, all 18 image responses, and
  capability cleanup succeeded for **both** RawINU and WeLoveManga.
- Chromium decoded the first and last page from each source at 1350 × 1920.
  Each chapter transferred 12,020,393 image bytes. No manga images were committed.
- After loading, JNI tmpfs remained 1% used; the disk reader cache was 24 MiB.
  The cleanup timer was active and its last service execution succeeded.
- Local Node suite: 183 passed. Production application and LMT builds passed.
- Relevant Python Suwayomi suite: 24 passed. Full local Windows suite ran 362
  tests, with four existing POSIX/SQLite portability errors and seven skips;
  Linux CI runs the full suite before publishing.
- Existing online browser contract suite passed at 320px and 1280px. Its fixtures
  are distinct from the real source/API/image checks above.

This repair introduces no ML changes and makes no additional inference claims.
