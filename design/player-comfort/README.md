# Player comfort and synchronized lyrics

The depth entrance is still transparent at time zero. Its first six-second pass
now reaches .70; subsequent ten-second pulses cover .26–.70 (amplitude .22 instead
of .09). The depth model/inference stays unchanged; this is a shader-timing edit.

HLS quality changes update the existing engine rather than detach/destroy/reload
its media source. Initial level selection uses manifest bitrates and connection
downlink with a conservative device fallback, without an extra bandwidth-test
fragment. ABR remains active in auto. Buffer targets are 75 s / 64 MiB on ordinary
devices, 40 s / 32 MiB on smaller-memory devices, and 15 s / 12 MiB in data saver.
The time ceiling contracts at higher manifest bitrates to respect the encoded-byte budget (allowing fragment granularity). HLS can buffer up to 90 s on ordinary devices, 60 s on smaller devices and 20 s in data saver at low bitrates. This is an ahead buffer, not a permanent download of an entire episode.
Real delivery speed, encoding support and source availability still matter.

Navbar controls share a 38 px vertical rhythm. Search and its expanded field use
one accent derived from the active palette; the brand and selected navigation are
neutral. Player menus keep the existing components, with larger labelled tabs,
focus trapping/return, stable content space, spring entrance and reduced-motion
support. Native select controls and all existing actions remain available.

Lyrics prefer exact title/artist matches from AMLL TTML DB, accepting timed files
only when the final cue fits the selected recording duration. The metadata index
is shared, low priority and cached for seven days; lyric documents stay in bounded
memory. MusicBrainz native-title aliases can improve matching. LRCLIB's exact
lookup checks recording duration within two seconds and provides line sync.
Cover/live/TV-size recordings can require another version or a user offset; no
uniformly spaced words are generated from line-only lyrics. The UI reports word
versus line precision and supports an offset and a local LRC/TTML file.

TTML is parsed as inert XML with size limits and no DTD/entities, script or HTML
insertion. Translation/romanization metadata is excluded from the sung words.
Whitespace between word spans is preserved. Animation reads the actual audio
clock, handles seeking/pausing and updates only the lyric component/CSS rather
than the whole player every frame. No audio, API key or Google token is uploaded
to a lyric provider. Provider failures never block playback.

Validation: pure Node tests cover LRC/enhanced timestamps, offset, matching,
fragment spacing and buffer/start policies. Browser fixtures use real React,
HLS.js, decoded video/audio and TTML to verify master-playlist continuity after
quality changes, position retention, navbar geometry, menu fit/focus and lyric
word progression/seek at 390/1440 px. Separately, real public provider requests
returned HTTP 200: one AMLL song parsed as 91 lines / 597 word timestamps, and
LRCLIB was CORS-readable. This is not a claim that all songs have word timing.

Primary references: https://lrclib.net/docs ,
https://github.com/amll-dev/amll-ttml-db/blob/main/instructions/ttml-specification-en.md ,
https://hlsjs.video-dev.org/api-docs/ .
