# HanimeTV through a Cloudflare Worker

Checked 2026-11-06.

## Why

HanimeTV search works from the Oracle VM, but every episode page and every
signed player API call on `hanime.tv` / `auth.hanime.tv` answers the datacenter
address with a Cloudflare challenge (`403`, `cf-mitigated: challenge`); the same
signed handshake succeeds from a home connection. A browser page cannot do the
requests itself: the handshake answer and the `hanime.tv/hls/...` playlists are
CORS-limited to `https://hanime.tv`. The open-source Stremio addon
[anime-src/hanime-stremio](https://github.com/anime-src/hanime-stremio) (August
2026) documents the same datacenter block and relays these two requests through a
Cloudflare Worker; MediaVault follows that design. Nothing solves or bypasses a
challenge: if HanimeTV starts challenging the Worker too, playback says so.

## Flow

1. The server signs the player handshake itself (`hanime_player` module:
   `x-signature`/`x-time`, AES-GCM sealed `{timestamp_unix, directive, slug}`).
2. `server/hanime_relay.py` posts it to the Worker's `/handshake`; the Worker
   (`workers/hanime-relay/src/index.mjs`) forwards it to
   `https://auth.hanime.tv/api/v11/handshake` with fixed `Origin`/`Referer`.
3. The `x-token` answer lists free sources (`kind: normal`, 360/480/720p) as
   tokenised `https://hanime.tv/hls/<id>/<token>` playlists. Premium sources are
   ignored.
4. `PublicHttp` routes exactly those playlist URLs through the Worker's
   `GET /hls/<id>/<token>`. The online player builds its usual adaptive master.
5. Segments (`*.htv-elidibus.com`, AES-128 MPEG-TS labelled `text/html`) and the
   key (`https://ct.htv-services.com/sign.bin`) are fetched by the server
   directly; their CDN serves Oracle. Plain AES-128 HLS is now accepted for
   online playback; SAMPLE-AES, KEYFORMAT DRM systems and session keys are not.

The Worker accepts only those two routes, requires `Authorization: Bearer
<RELAY_SECRET>` (compared by SHA-256 digest), limits bodies to 16 KB and
playlists to 1 MB, forwards no cookies and adds no CORS headers.

## Setup

```powershell
cd workers/hanime-relay
npx wrangler@4.20.0 login
npx wrangler@4.20.0 deploy
# a random secret of at least 32 characters, kept outside Git:
Get-Content -Raw ..\..\.codex-local\secrets\hanime-relay-secret | npx wrangler@4.20.0 secret put RELAY_SECRET
```

On the VM, add to the importer's Compose `.env`:

```
HANIME_RELAY_URL=https://mediavault-hanime-relay.<account>.workers.dev
HANIME_RELAY_SECRET=<the same secret>
```

The free Workers plan (100,000 requests per day) is ample: an episode needs one
handshake and one playlist per chosen quality.

## Verification

`tests/test_hanime_relay.py` covers relay settings, the signed request shape,
free-source filtering and URL allowlist, challenge/secret errors, the no-relay
message (no headless browser attempt), the `PublicHttp` playlist route,
AES-128 versus DRM manifests, the adaptive master and the segment-host
exception. Live from the Oracle VM through the deployed Worker:
`overflow-season-1` handshake 0.5 s with 720/480/360p, 14 KB playlist via the
Worker, first segment `200` directly from the CDN.
