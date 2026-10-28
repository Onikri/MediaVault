# Suwayomi and the MediaVault reader

Suwayomi Server **v2.4.2366** runs beside the existing importer on its private Docker network. The official ARM64 image is pinned by multiarch manifest digest `sha256:1fac27c387dc2ea9949e1a01ad7f6d6de9d72d3988338a95476748e5c45c4582`.

Upstream: https://github.com/Suwayomi/Suwayomi-Server (MPL-2.0; Android compatibility components include Apache-2.0). MediaVault uses its REST API, retains the existing content-first reader and translation engine, and links upstream in source settings. No Suwayomi WebUI source has been copied. EPUB.js and PDF.js remain the book engines.

## Operation

After the existing importer has been updated to backend v14, the maintainer runs `python3 deploy/oracle/install-suwayomi.py` on the VM. It discovers the current Compose project, preserves existing overlays, adds `suwayomi.yaml`, checks the service, and recreates only the importer to enable its private adapter. It leaves Oracle shape/resources, Caddy routes, Drive/OAuth configuration, library encryption and existing ML workers intact. A failed readiness check leaves the importer unchanged; a failed importer check restores the previous Compose configuration. Logs and rollback information are private under `/opt/mediavault-suwayomi`.

No host port or admin UI is exposed. Basic authentication is required internally. Credentials are generated on the VM in `/data/suwayomi-auth.json`, owned by UID1000 with mode0600. Suwayomi gets its own data directory, **not** Drive credentials or importer data. JVM heap768MiB, container limit1536MiB/1CPU, source concurrency2; automatic downloads and whole-library updates are disabled. Browser/KCEF and challenge-solving services are disabled. A source requiring browser login, subscription or a challenge may remain unavailable.

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
