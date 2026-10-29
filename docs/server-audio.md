# Server audio playback

POST `/music/play` accepts a single public HTTPS YouTube recording URL under the
existing owner session. yt-dlp resolves an audio-only HTTPS M4A/WebM format. The
browser receives only a short-lived `/online/<capability>/<resource>` URL,
metadata and the real audio MIME type. No arbitrary `/stream?url=` endpoint is
exposed. Google login tokens/cookies are not forwarded to yt-dlp or media hosts.

Both initial CDN addresses and redirects must be public googlevideo.com
`/videoplayback` URLs. The existing stream handler preserves Range/206,
Content-Range, Content-Length and Accept-Ranges and closes upstream connections
on disconnect. Only bounded extractor metadata is cached in memory; media bytes
are streamed without persistent audio files. There are two extractor slots, a28s
extractor deadline and a65s total preparation budget, plus the existing four
playback capabilities per owner. The browser allows75s for preparation.
Cancelled preparations release capabilities; close/track changes release the
previous capability on the frontend. Metadata refreshes after ten minutes;
playback capabilities last up to two hours, bounded by the upstream signed URL
expiry. Expired links can be prepared again.

URL extraction must preserve the selected format's `available_at`. YouTube may
issue a signed URL before that URL can be read; the server observes its not-before
timestamp just as yt-dlp's downloader does. Only then does it request bytes0–31
and validate HTTP206, Content-Range, MIME and the M4A/WebM header. Denied URLs
never enter the cache or become playback capabilities. This is not an account
login or PO-token mechanism. Source implementation:
[yt-dlp downloader](https://github.com/yt-dlp/yt-dlp/blob/2026.10.21/yt_dlp/downloader/common.py).

The Oracle image includes Node22 for yt-dlp's EJS runtime. yt-dlp and the Node
image are version-pinned; updates are reviewed and deployed, rather than a live
`pip install -U` mutating the running container. yt-dlp alone does not guarantee
that YouTube will serve an Oracle datacenter IP. Verification, access restrictions
and missing formats are reported as preparation failures. The official visible
YouTube player remains an explicit alternative. Spotify keeps its own SDK and
account permissions. Collapsing server audio keeps playback running; collapsing
the official YouTube embed still pauses its video.

Protocol references: [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[EJS runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

`test_music_audio.py` and `youtube-audio.test.mjs` test fixture resolver/API and
proxy boundaries. `music-audio-browser.cjs` decodes real generated AAC and checks
seek/collapse/pause/cleanup at390px and1440px, with the resolver explicitly mocked.
Actual YouTube extraction and streamed bytes from Oracle are checked separately;
fixture success must never be described as successful YouTube playback.
