# Source network services: Japan route and Byparr

The importer's source transport reaches the Japan exit and the challenge
solver through three private services on the Oracle VM. They are their own
Compose project, `mediavault-network`, installed from
`deploy/oracle/network/` by `deploy/oracle/install-network-services.py` into
`/opt/mediavault-network`. Nothing in them depends on Suwayomi: no
`depends_on`, no Suwayomi volume, no Suwayomi setting. They only join the
importer's Docker network (`oracle_default`) so the importer reaches them by
name. No host port is published.

This page is the contract between these services (agent A, infrastructure)
and the server transport (agent B).

## Services

| Service | Container | Names on the network | Port | What |
| --- | --- | --- | --- | --- |
| `jp-router` | `mediavault-jp-router` | `jp-router`, `suwayomi-jp-router` | 8080 | HTTP proxy (CONNECT) |
| | | | 1080 | SOCKS5 (use `socks5h`, hostnames must reach the router) |
| `jp-vpn` | `mediavault-jp-vpn` | `jp-vpn`, `suwayomi-jp-vpn` | 8090 | Exit status: `/status`, `/health` |
| | | | 1081 | Internal SOCKS worker (router only; do not call) |
| `byparr` | `mediavault-byparr` | `byparr` | 8191 | FlareSolverr-style solver API |

`suwayomi-jp-router` stays an alias because Suwayomi's SOCKS setting and
`/data/manga-source-routes.json` (`httpProxy`, checked literally by
`server/manga_network_routes.py`) use that name. New code should use
`http://jp-router:8080`; when B accepts both names in
`manga_network_routes.configuration()`, the manifest can switch to
`jp-router` and the legacy alias can go after Suwayomi is removed.

## Routing semantics

- The router decides per destination host (the CONNECT/SOCKS target). Hosts in
  the whitelist (`HOSTS` in `deploy/oracle/network/jp-gateway/gateway.py`,
  published to the importer as `/data/manga-source-routes.json`) leave from
  Japan through the VPN. Every other host leaves directly from the router,
  i.e. from the Oracle address (`141.144.225.42`, `loc=DE`).
- A host must be in both lists to be routed: the gateway whitelist (router)
  and the manifest (transport). The installer writes the manifest from the
  same tuple, so they cannot drift if hosts are added there and re-installed.
- Redirects are decided again per hop: a redirect from a routed host to a host
  outside the list goes direct. The transport should keep evaluating
  `routed(url)` per hop (it does today) and keep same-host redirect rules for
  `Route(japan=True)` sources.
- DNS for routed hosts is resolved inside the VPN (Japanese answers);
  the router resolves direct hosts itself.

## Exit identity

`GET http://jp-vpn:8090/status` (always 200) and `GET http://jp-vpn:8090/health`
(200 only when ready and fresh, otherwise 503) return the same JSON:

```json
{"ready": true, "state": "ready", "country": "JP", "exit": "106.173.94.75",
 "generation": 4, "since": 1794939810.85, "endpoint": "106.173.94.75:1223/tcp",
 "failures": {"tunnel": 0, "dns": 0}, "time": 1794939840.86, "age": 3.1, "fresh": true}
```

Not ready: `{"ready": false, "state": "reconnecting", "reason": "tunnel|tun-down|dns|vpn-exit|vpn-connect|publisher|country|rotate", "lastExit": "…", "generation": 4, …}`.

- `generation` is a monotonic integer persisted in the gateway state. It
  increases whenever a new VPN session becomes ready **and** whenever the exit
  IP changes inside a session. It never decreases across restarts.
- Bind anything a site ties to the client IP (Byparr cookies + user agent,
  clearance tokens, guest sessions) to `(domain, generation)` for routed
  domains and to `(domain, "direct")` otherwise. When `generation` differs
  from the one a cached solution was made under, drop it and solve again.
- Read `/status` before using a cached solution for a routed domain (cache
  the answer for at most 30 s) and again after any routed request fails.
- `/status` follows the tunnel within about a second when the tunnel device
  disappears and within one check interval (30 s) otherwise. The router's
  answer (below) is the immediate signal; treat it as authoritative.

## Failure contract

When the tunnel is down, reconnecting or rotating, the router does **not** fall
back to a direct connection for routed hosts:

- HTTP proxy: the CONNECT is answered `503 Service Unavailable` (Python
  `requests` raises `ProxyError … Tunnel connection failed: 503`). Measured
  12–40 ms while reconnecting; the first request caught by a stalled tunnel
  waited 15 s (GOST's dial timeout) before the same 503.
- SOCKS5: the connect reply is a failure code; the client gets a connection
  error immediately.
- The transport maps both to a **temporary** error for that source
  (`SourceTemporaryError`, "Японский маршрут временно недоступен"), never retries
  a routed host directly and never quarantines the source for a long time on
  this error alone. Keep request timeouts ≤ 30 s.
- If `/data/manga-source-routes.json` is missing or invalid,
  `configuration()` returns `{}` and `Route(japan=True)` requests currently go
  direct. B should turn that into the same temporary error for sources that
  require Japan.

Gateway recovery after a failure took 14–52 s in the tests below; VPN Gate is
volunteer-run, so an occasional longer outage (a full pass over dead
endpoints) is possible. Logins and paid chapters are not bypassed by this
route; they keep their explicit statuses.

## Byparr

Image `ghcr.io/thephaseless/byparr@sha256:c66fa161187b8fa527bfad7eefa2647ea1c553f77df68cbffd6fe83366d1787b`
(Byparr 3.1.1, revision `b041dd2`), 1 CPU, 2.5 GiB, 1024 pids, private only.

`POST http://byparr:8191/v1` with JSON `{"url": …, "maxTimeout": 60000}`.
Every request launches a fresh browser context, navigates, solves a challenge
if one is shown, waits for network idle and returns
`solution.{url, status, cookies, userAgent, headers, response}`. A trivial page
took 3.6 s.

Supported, measured on the VM:

| FlareSolverr feature | Byparr 3.1.1 |
| --- | --- |
| `request.get` with `url`, `maxTimeout` (<1000 = seconds, else ms) | yes |
| `blockMedia`, `returnOnlyCookies` (Byparr extras) | yes |
| Per-request proxy | yes, via headers `X-Proxy-Server` (+ `X-Proxy-Username`, `X-Proxy-Password`), not the body `proxy` field |
| `cmd` | ignored: every call is a GET navigation |
| `request.post` + `postData` | **no**: silently performed as GET; never send POSTs |
| `sessions.create` / `sessions.list` / `sessions.destroy` | **no**: HTTP 502 (`Invalid url "https://"`) |
| `session`, `cookies` in the request | ignored |

So the transport owns session state: keep the returned cookies + user agent
per `(domain, generation)` and reuse them with plain HTTP until the site
challenges again. For a routed (Japanese) domain send
`X-Proxy-Server: http://jp-router:8080`; only whitelisted hosts then leave
from Japan, the rest of the page loads direct. The browser keeps
`BROWSER_TIMEZONE=Europe/Berlin` even behind the Japan proxy.

Health: `GET /docs` (cheap). Do not poll `GET /health`: it launches a browser
for google.com each time. Keep at most two concurrent solves.

## Operations

- Install / migrate: `sudo python3 deploy/oracle/install-network-services.py`
  (takes `/opt/mediavault/deploy.lock`, refuses while imports are active unless
  `--allow-active`). It builds `mediavault-jp-gateway:<sha12 of Dockerfile+gateway.py>`,
  starts the new gateway beside the old one, swaps the router only after the
  gateway is ready, checks the route from the importer and rolls back on failure.
- State: `/opt/mediavault-network/state/jp` (`status.json`, `generation`,
  `last-good.ovpn`, `openvpn.log`); backups/logs in `/opt/mediavault-network/backups/<UTC>`.
- Restart without Suwayomi: `docker compose --project-directory /opt/mediavault-network -p mediavault-network restart`
  (or `up -d`). Rotate the exit: `docker exec mediavault-jp-vpn python /app/gateway.py rotate`.
- Logs: `docker logs mediavault-jp-vpn` (JSON lines: status changes, `tunnelCheckFailed`,
  `dnsCheckFailed`, `exitChanged`, `session` outcomes).

## Why the gateway kept reconnecting (2026-11-17)

48 h of logs of the old gateway: 13 sessions, median 30 min, and a 54-minute
outage (17:01–17:55 UTC on 2026-11-17). Every session was ended by **one**
failed 45-second health probe, 10 of 13 by DNS (9 × `curl: (28) Resolving timed out`,
1 × `Could not resolve host`).
VPN Gate pushes `redirect-gateway def1`, so the container's DNS (`1.1.1.1` via
Docker's resolver) runs through the volunteer tunnel, and a single slow lookup
tore down a working tunnel. Reconnects were then slow because the candidate
list was the feed fetched when the previous session started (up to 20 h old):
214 attempts failed to connect and 184 were refused with `403` by a publisher
check, endpoints that were retried every round.

Fixes in `gateway.py`: the tunnel is checked by IP (`https://1.1.1.1/cdn-cgi/trace`,
which needs no DNS) and dropped only after 3 consecutive failures; DNS is checked
separately and drops the tunnel only after 6 consecutive failures; a second
resolver (`8.8.8.8`) was added; failed endpoints are skipped for 30 min; the feed
is refreshed when older than 15 min; the last good endpoint is retried first;
a lost `tun0` is reported at once. MTU was not the cause (no evidence in the logs).

## Measured on 2026-11-17 (isolated network, no Suwayomi, no importer)

- Ready 30 s after start; Docker health `healthy` for both containers.
- Through `jp-router:8080`: `soraraw.com` trace `loc=JP` (exit = the gateway's
  `exit`); SOCKS5 `mangafire.to` `loc=JP`; `www.cloudflare.com` `loc=DE`
  (`141.144.225.42`, direct, as intended); Comic Ryu search 200, Sokuyomi 200,
  LINE Manga 200, FOD 301; the same through the `suwayomi-jp-router` alias.
- Rotation: route answered 503 in 12–36 ms during reconnect; new exit after
  14 s and 37 s (generation 1→2, 3→4).
- Stalled tunnel (outer VPN traffic dropped): first request 503 after 15 s,
  then 503 in ms; `/status` `tun-down` immediately; new exit after 45–52 s.
