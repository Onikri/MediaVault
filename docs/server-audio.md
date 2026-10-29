# Server audio playback

POST `/music/play` accepts a single public HTTPS YouTube recording URL under the
existing owner session. yt-dlp resolves an audio-only HTTPS M4A/WebM format. The
browser receives only a short-lived `/online/<capability>/<resource>` URL,
metadata and the real audio MIME type. No arbitrary `/stream?url=` endpoint is
exposed. Drive/Google API tokens are not forwarded to yt-dlp or media hosts. An owner can
explicitly connect a YouTube session as described below; no browser profile is
read automatically.

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
and missing formats are reported as preparation failures. The music module has
no YouTube iframe, iframe API, browser Spotify playback SDK or provider-player
fallback. Songs selected from a Spotify playlist use their title and artist to
resolve audio through Oracle as well. Playlist/account management remains a
separate OAuth feature. Closing details or changing browser visibility does not
pause audio. Details open only when the user requests them; errors stay compact
and Play retries the Oracle preparation.


Protocol references: [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[EJS runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

`test_music_audio.py` and `youtube-audio.test.mjs` test fixture resolver/API and
proxy boundaries. `music-audio-browser.cjs` decodes real generated AAC and checks
seek/collapse/pause/cleanup at390px and1440px, with the resolver explicitly mocked.
Actual YouTube extraction and streamed bytes from Oracle are checked separately;
fixture success must never be described as successful YouTube playback.

Direct external audio URLs use owner-authenticated POST `/music/remote`, not a
browser connection to the media host. The server validates public HTTPS addresses
and redirects, actual audio signatures/MIME, Range support and a256MiB file limit
before granting a short-lived music-file capability. Local device files and
already-decrypted personal-library media stay on the device.

Owner authentication uses GET/PUT/DELETE `/music/youtube/session`. The profile
accepts a user-selected Netscape cookies.txt export and immediately verifies
Otonoke through the existing real audio preflight. Only unexpired youtube.com
cookies are kept; other Google/website credentials are discarded. The session is
AES-GCM encrypted using the existing private TaskStore. API replies contain only
configuration status and a timestamp. yt-dlp receives a per-request0600 temporary
copy in Linux container tmpfs, deleted on success, errors and timeouts; cookies
never reach CDN requests. A container crash cannot persist that decrypted copy
in the /data volume.
Replacing/removing a session revokes cached YouTube URLs and music capabilities.
Requests running across a session change fail rather than recaching old access.

Upstream documents cookies as the supported yt-dlp login method; its old OAuth
flow no longer works: [YouTube authentication](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).
A valid session must be supplied by the owner; a Google profile login to MediaVault
alone does not authorize the server on YouTube. Fixture authentication tests are
not evidence of actual authenticated Otonoke playback.
