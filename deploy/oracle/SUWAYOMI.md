# Suwayomi and the MediaVault reader

Suwayomi Server **v2.4.2366** runs beside the existing importer on its private Docker network. The official ARM64 image is pinned by multiarch manifest digest `sha256:1fac27c387dc2ea9949e1a01ad7f6d6de9d72d3988338a95476748e5c45c4582`.

Upstream: https://github.com/Suwayomi/Suwayomi-Server (MPL-2.0; Android compatibility components include Apache-2.0). MediaVault uses its REST API, retains the existing content-first reader and translation engine, and links upstream in source settings. No Suwayomi WebUI source has been copied. EPUB.js and PDF.js remain the book engines.

## Operation

After the existing importer has been updated to backend v14, the maintainer runs `python3 deploy/oracle/install-suwayomi.py` on the VM. It discovers the current Compose project, preserves existing overlays, adds `suwayomi.yaml`, checks the service, and recreates only the importer to enable its private adapter. It leaves Oracle shape/resources, Caddy routes, Drive/OAuth configuration, library encryption and existing ML workers intact. A failed readiness check leaves the importer unchanged; a failed importer check restores the previous Compose configuration. Logs and rollback information are private under `/opt/mediavault-suwayomi`.

No host port or admin UI is exposed. Basic authentication is required internally. Credentials are generated on the VM in `/data/suwayomi-auth.json`, owned by UID1000 with mode0600. Suwayomi gets its own data directory, **not** Drive credentials or importer data. JVM heap768MiB, container limit2304MiB/1CPU, source concurrency2; automatic downloads and whole-library updates are disabled. The official image launcher enables bundled ARM64 KCEF and Xvfb, which LibGroup uses even when reading browser storage for a public request. Challenge-solving services remain disabled. Actual account/subscription requirements remain distinct from a broken runtime.

Existing deployments created with the direct Java/headless entrypoint need
`sudo python3 deploy/oracle/enable-suwayomi-browser.py`. It checks the existing
private pinned image and bundled browser, refuses active imports, saves private
Compose/config backups, and recreates only Suwayomi. Failed readiness restores
the original files and service. OAuth, Drive keys and installed extensions are
preserved. Source-list readiness confirms the service, not successful website
authentication; verify real search, chapters and image retrieval separately.

Backend v17 also retries a failing MangaDex chapter-list adapter through the
existing public MangaDex API, preserving the exact title UUID and language.
Native chapter URLs then use the normal online/download path. Empty or removed
chapters are reported separately from a server failure. The browser inspection
budget covers the bounded server request instead of aborting it at20seconds.

MangaLib's native public adapter supplies the mandatory `Site-Id:1` header and
public reader referer. The global search retains MangaLib's installed source ID
and falls back to this same-site adapter when LibGroup fails; native title and
chapter URLs then support the existing reader and CBZ export. This does not
substitute a different website or remove a failing source from the selector.
Canonical source names and `releaseDateString` distinguish a work from fan works
that reuse its franchise as an English alias. The one-time discovery-cache
migration expires only ambiguous legacy MangaLib metadata/query entries and
their completed search snapshots; private libraries and other source caches
are preserved. Automatic selection can recover to the native adapter when it
arrives after an initial failed source. An explicit user selection is preserved.

Backend v18 adds a public NovelCool RU HTML reader. If its extension fails,
the bridge resolves only the identical manga identifier's indexed public URL
on `ru.novelcool.com`; it does not accept arbitrary fallback URLs. It parses
volume/chapter labels, preserves chapter0 and fractions, and follows the site's
ten-image reader pagination only within the selected chapter (maximum500pages).
Next-chapter navigation and external redirects cannot become extra pages.
The normal online reader and CBZ exporter consume these native chapter URLs.
Live device checks found686chapters for Naruto and58images across chapter1
pagination. A real CBZ contained58images,5881644bytes and valid ZIP CRCs; the
search/read/archive pass took8375ms. These live checks are separate from the
sanitized HTML contracts. Oracle's public HTTP client and ordinary Chromium
instead received an HTTP200 response containing only a155-byte "404 Not Found"
HTML placeholder. This source is not certified working from that VM; it remains
selectable and its failure is reported. Do not report the device run as VM proof.

## Public source device transport · v20

When NovelCool serves an empty placeholder to Oracle but works on the owner's
device, `server/source_relay_worker.py` supplies that same public site over an
outbound HTTPS connection to the existing backend. The native adapter uses the
live transport for HTML, reader images and complete CBZ files. It does not
substitute MangaLib or another website for a manually selected NovelCool source.

The worker creates an Ed25519 key inside `.codex-local/secrets/`; only its public
key is installed on the VM in `/data/source-device-public-keys.json` as a mapping
from device ID to base64 public key. Google sessions, Drive keys, browser cookies
and source accounts are never passed to the worker. Every poll/result is signed
over method, path, time, nonce, exact bytes and result metadata; replayed or
expired signatures fail. Revoking a device removes its public-key entry.

Only public NovelCool RU title/chapter paths and the observed `*.movietop.cc`
comic-image paths are permitted. Both device and backend validate destinations;
there is no arbitrary URL proxy, login forwarding, incoming PC port or retained
page store. Twelve bounded in-memory tasks at most, three device workers, 28s
request lifetime and12MiB image limit bound resource use. Results are uploaded
in signed ordered256KiB chunks, preserving the existing512KiB Caddy/API request
limits even for large HTML or page images. Completed/timed-out
tasks discard their bytes. A missing device leaves the ordinary source request
path available; its failure remains an error rather than an empty chapter list.

Run `scripts/start-source-device.ps1` on this Windows checkout to launch the
hidden worker. Its PID, logs, temporary data and signing key stay on drive D in
`.codex-local`. The device must remain running/online to serve this route. Source
transport contract tests are separate from real Oracle→device→reader/CBZ tests.

The Keiyoushi repository uses `https://github.com/keiyoushi/extensions/raw/repo/index.pb`; the legacy JSON index currently contains migration placeholders. On 2026-10-28, the local server returned **1435 extension packages**. This is not a count of verified working sites. Only a small RU/EN/JA/KO set is installed initially. Owners can add catalogued packages in **Import → Manga → More sources**. Source code runs inside the restricted Suwayomi container; arbitrary APK uploads are not exposed.

Search fans out to installed sources with bounded concurrency and title-identity matching alongside native adapters. Manga IDs and source IDs are not interchangeable; source IDs stay strings. A chapter's source index is distinct from its printed number (including chapter0/extras). Identifier URLs under `/__manga/suwayomi/` are not HTTP proxy endpoints: the importer validates its own origin/path, maps numeric IDs to private Suwayomi routes, and checks actual image signatures and size limits. The browser gets only existing expiring, owner-created `/online/` capabilities. The same images can be packed into CBZ and encrypted for Drive. No chapter is downloaded to Drive merely to read online.

## Personal translation key

**Remember on this device** encrypts the Google API key using AES-GCM256 and an account-scoped, non-exportable Web Crypto key in IndexedDB, for90days. Additional authenticated data binds ciphertext to the profile and provider. Plaintext keys do not enter cookies, localStorage, saved reader settings or the backend. The direct Google translation mode still sends requests from the device. Session-only use remains available. Explicit profile logout removes the saved personal key; library lock clears memory and allows restoration after reopening. **Forget this device** clears remembered libraries, account data and API keys. This is browser-managed encryption at rest, not an HttpOnly cookie or protection against malicious same-origin JavaScript.

Existing remembered-profile and wrapped-library-key support remains in place. The secret library phrase itself is never stored. Clearing site storage or changing the site origin requires signing in and remembering the device again.

## Verification

`python -m unittest discover -s tests -p 'test_*.py'`, `npm test`, `npm run test:trusted`, `npm run test:suwayomi`, `npm run test:manga`, `npm run test:direct`, `npm run test:online`, and `npm run test:reader` cover private-route boundaries, exact identity, chapter numbering, CBZ integration, encrypted IndexedDB reload/account isolation, installation UI and existing readers. Real upstream source availability is verified separately; fixture tests do not assert all packages work.

## Language packs and search coverage · backend v15

The owner can install every non-obsolete RU/EN/JA/KO package, including packages
marked `all`, using **Import → Manga → More sources → Connect all RU/EN/JA/KO**.
Installation runs sequentially in the importer background, with a private atomic
journal at `/data/suwayomi-install.json`. Closing the tab does not stop it. A server
restart is shown as interrupted; starting again queries the actual installed
catalog and retries missing/failed packages. No arbitrary APK URL is accepted.

Endpoints (existing owner authentication is required):
- `POST /manga/bridge/install-pack`, body `{"languages":["ru","en","ja","ko"]}`;
- `GET /manga/bridge/install-pack`, progress and failed packages;
- `POST /manga/bridge/search`, the usual title/language/format plus `bridgeOffset`
  and `bridgeLimit` (default8, maximum16).

Installing hundreds of extensions does not trigger a global download or library
update. The former silent first32-source search cap is removed. Title search now
reports `checked`, `nextOffset`, `totalSources` and `hasMore`; the reader/import
screen offers **Check next sources**. Source order is stable and language-specific.
Each request has a bounded window and time budget; unstarted sources remain for
the next request. This makes every installed supported source reachable without
sending hundreds of simultaneous requests to the free Oracle VM. Unavailable
sites and empty searches remain distinguishable from pending sources.

`install-suwayomi.py --all-languages` requires v15 and verifies that no imports
are active before changing Compose. It installs the private service and initial
sample extensions; bulk installation is then started through the owner API/UI.
The checkbox/button action is not a claim that every website works: installation,
search, chapter listing and actual image retrieval are separate checks.

Tests of language-pack selection, retry, journal persistence and search beyond32
sources use explicit provider fixtures. The browser contract checks individual and
bulk installation, progress and continued search at360/1440px. Live Oracle/source
results are recorded separately; test pages and private server logs stay outside
Git in `.codex-local/`.
