# Anime playback quality and Russian catalogue repair — 2026-10-30

Alloha's film player initially requests its saved/default 480p selection. Its
signed HLS master contains only that selection, not the complete quality ladder.
The source browser reads the initialized active audio source's explicit signed
quality/URL map. This avoids associating delayed WebSocket responses with the
next quality selection. Older players fall back to their published quality buttons.
It does not synthesize CDN addresses or switch translations/audio. The boot
stream cannot override the labelled 2160p stream when online playback picks best.
Requests keep the publisher Referer during quality inspection (server version 34)
as well as during playback. Older servers still receive the original request shape.
Temporary Chromium profiles and cache default to the project's .codex-local.

Film translation enumeration now handles Kodik's movie-translations-box and
Alloha's movie/cut/translation table. Alloha keeps the active film cut and its
published numeric translation IDs; Ukrainian labels remain distinct. Kodik's
published subtitle flag is preserved. No higher Kodik quality is invented.

Added public catalogue adapters for AnimeGO Online (animego.online) and Anigoo
Online (www.anigoonline.ru). The former's published relay slots use the same
validated GET envelope as YummyAnime. AniDub cards retain the release anchor
instead of accidentally selecting a nested year link. Conservative title matching
ignores release counters and explicit film labels while retaining sequel, year
and external-ID checks. Search can use a shorter title query, then validates each
hit against the exact selected work. Navigation year lists are no longer accepted
as the release year. AnimeVost's known advertisement iframe is excluded.
Provider diagnostics distinguish a found title without confirmed players from a
confirmed variant and no longer show an obsolete no-match message for a success.

## Verification

Actual source network checks were made from the Windows workstation, not the VM:
[metadata-only report](benchmarks/anime-reze-qualities-2026-10-30.json).
For Chainsaw Man Movie: Reze-hen, Alloha published 360/480/720/1080/1440/2160
menu choices. Every corresponding HLS manifest was fetched; the top variant was
3840x1604 (cinema crop). Kodik's tested Russian dub published 360/480/720.
Each top stream returned HTTP 206 and a 1024-byte media sample. This verifies
resolution discovery, manifests and media access, not complete-film playback,
all dubs, every provider, or performance on the VM. Signed URLs stay private.
Discovery was also exercised against live public catalogues; exact counts and
remaining providers without confirmed players are recorded in the report.

Separate controlled tests execute real Chromium against fixture responses to
exercise menu selection, absent 8K streams, and translation preservation. Python
contracts cover movie tables, publisher headers, catalogue anchors, title/year
validation, advertisement exclusion, and best-quality online selection. Node
unit tests, voice/online browser suites and the production build pass. The
existing POSIX service.key permission assertion cannot run unchanged on Windows;
the complete Linux suite is required in CI before release. No ML inference is
part of this playback change.

Live VM verification initially exposed an intermittent 1440p maximum caused by
menu-response timing. The active source map is authoritative and does not switch
audio tracks. A dedicated Chromium fixture verifies all six quality URLs before
any high-resolution media request has completed.
