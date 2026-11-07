# Alloha → encrypted Google Drive

This path applies only to Alloha imports. Other players retain their existing
downloaders. No Cloudflare service, extension, local helper or client-side model
is required.

## Data path

1. The existing native browser session opens the published iframe from its real
   publisher context. One verified browser profile stays fixed for that session.
2. A private loopback HTTP server presents checked HLS manifests and segments to
   ffmpeg. Only the browser transport contacts the upstream CDN. CDN URLs,
   session cookies and request headers never reach ffmpeg or Drive metadata.
3. ffmpeg copies the original codecs into fragmented MP4 on stdout. It does not
   transcode. The initial header sample is bounded to 4 MiB and immediately
   deleted after probing video dimensions and the audio track.
4. VaultDrive reads 4-MiB chunks, encrypts them with the existing AES-GCM format
   and uploads at most two chunks concurrently. Slow Drive writes apply natural
   backpressure through the pipe. No complete film or plaintext segment cache is
   written to disk.
5. Source refusals/expired sessions use the existing full-session renewal and
   profile health handling. The selected audio, quality, playlist layout and
   initialization data must remain consistent. No synthetic viewing progress
   or invented browser fingerprint is used.
6. EOF alone is insufficient: ffmpeg must exit successfully, finish its progress
   report, preserve the audio/video tracks, read all selected resources, and
   write the final MP4 index. The duration check allows up to 0.5% drift
   between the declared HLS segment lengths and the final packet timestamps.
   Only then are the encrypted recovery manifest and catalogue item published.
   Published nominal quality and measured dimensions are stored separately,
   since cinematic video can have cropped black bars.

## Recovery

Confirmed remote chunk IDs, IVs, lengths and hashes can be saved in a small,
AES-GCM-encrypted `stream.enc.json` checkpoint in the task's private cache.
There are no credentials, plaintext video or signed CDN URLs in this index.
After a worker restart, the producer replays the source prefix and checks each
chunk hash; matching encrypted Drive chunks are reused without uploading them
again. This is not a promise to avoid rereading the source after process loss.
Changed stream identities or differing prefixes are rejected rather than mixed.
In-session renewal continues the running pipe without replaying earlier video.

Successful publication removes the checkpoint. Incomplete remote assets remain
private and outside the catalogue while a resumable checkpoint exists. Such
indexes are excluded from the plaintext-segment cache's automatic age pruning.

## Verification boundaries

Python tests use real ffmpeg, remuxing, AES-GCM and file verification with mocked
CDN/browser and Drive transports. They cover audio, bounded disk storage, a
source refusal followed by session renewal, incomplete-file rejection and
encrypted checkpoint recovery across a new VaultDrive instance. The existing
browser-crypto interoperability tests verify the unchanged chunk format.
There is no ML inference in this pipeline.

The live Reze dub import used the published 1440p Alloha stream. The completed
5,550,108,545-byte file (2560 × 1070 with audio) was authenticated and read back
from Drive across all 1,324 chunks. FFmpeg read the entire archive without
errors. The measured 5,999.552-second timeline differed by 15.968 seconds from
the sum of the source's segment durations.

For browser playback the service worker reads the encrypted head and tail
blocks to build front seek indexes for video and audio. This virtual MP4 view
serves normal byte ranges without changing the archived bytes or their
checksum. In the live Chromium check, the React player decoded both tracks
and resumed playback after seeks to 50:00 and back to 0:30.
