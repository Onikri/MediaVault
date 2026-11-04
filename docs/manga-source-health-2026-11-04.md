# Manga reader availability — 2026-11-04

## Behavior

A chapter count is no longer proof that a source can serve pages. New clients ask
`/manga/summary` to verify one complete image of the selected title before showing
an ordinary reader choice or automatically selecting it. Checks share a bounded
cache and four server slots; the browser submits two checks at once. No image
bytes are persisted by these checks. Failed title checks appear separately with
an explicit retry. Manual inspection also verifies pages before enabling reading.

Installed source health is recorded as public metadata in the existing
project-local discovery bind mount. Default discovery and source filters omit
recently failed sources. Existing cached searches cannot reintroduce a failed
provider. A manual refresh/explicit source selection allows another attempt;
health expires after six hours. An empty catalogue sample is inconclusive, not
proof that a source is broken. Full successful title probes can restore health.
The authenticated health endpoint and source manager show stages and timestamps.

For supported HTML readers, saved Suwayomi title/chapter references resolve to
the same site's native adapter when its extension fails. Work, language, source
host and selected chapter identity are preserved; there is no substitution with
another provider or scanlation. LibGroup and MangaDex retain their native paths.

MangaBall additionally tries its own `server2` image-proxy endpoint, as used by
its public web reader. Public chapter JSON must match the saved title, chapter,
language and page order. Neither arbitrary client URLs nor cookies are forwarded.
The reported Lodoss/Suicune image is still HTTP403 even through that official
reserve endpoint (`Upstream error 403`). MangaBall is therefore excluded from
ordinary discovery until a real page check succeeds or availability is retried.
This change does not claim to have removed the site's own CDN restriction.

## Live audit

`scripts/audit-manga-sources.py` audited all 770 installed RU/EN/JA/KO sources on
Oracle, with at most eight concurrent workers. Each attempts popular/search,
chapter retrieval and one actual image, sampling up to two works. The first pass
verified 452 sources. A second pass on earlier chapters restored another 42:
494 image samples worked, 255 sources failed, 21 had no suitable test entry.
These are bounded samples, not a guarantee that every chapter of every work is
open. Registry metadata and logs remain in the VM project's `.codex-local`.

A separate native-adapter audit checked 19 adapter/language combinations using
Naruto and Tower of God. Real images loaded through MangaPoisk, MangaHub,
MangaChan, MangaLib, MangaPill, MangaKatana, MangaRaw, Naver Webtoon and Naver Best
Challenge. MangaBuff, MangaDex, Toonkor and the sampled HentaiLib chapter failed;
other tests found no matching entry and are inconclusive. Native per-title
verification applies regardless of these sample results.

## Local verification

61 relevant Python tests passed: real health SQLite/cache handling, fixed
MangaBall identity/path restrictions, source filtering and existing import/export
contracts. Provider responses in those tests are fixtures. The browser regression
uses real React at 360/1440px with fixture readability responses; it checks that
metadata-only/failed readers are not normal choices, retries stay available and
only two checks run at once. Nine relevant Node tests and production builds pass.
Actual upstream availability is documented separately above. No ML changes or
inference tests are part of this work.
