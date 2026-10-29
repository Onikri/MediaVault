# Source search and reader recovery — 2026-10-29

The source catalogue and the page reader are separate requests. Returning chapter
metadata does not prove that chapter images are publicly readable. This release
repairs the same-source paths without substituting an unrelated provider.

* HentaiLib and MangaLib use their own public LibGroup API context (`Site-Id` 4
  and 1), referer, image-server selection and canonical URLs. Discovery avoids
  the broken Android WebView initialization path. Saved Suwayomi title/chapter
  links map back to the exact cached source identity, chapter and branch.
* MangaDex search and chapter feeds explicitly include all content ratings and
  retain age metadata for the existing UI filter. The native API supplies the
  language variants instead of depending on hidden extension preferences.
* Exact public title aliases enrich queued source queries in the appropriate
  script. For example, a Russian source supplies Moby Dick and 모비딕 for Белый Кит.
  MangaDex-only Russian searches can resolve that public identity as well.
  Publication-year and canonical-title checks still reject unrelated fan works.
* A changed alias query is retried if an in-flight source already returned an
  empty or unrelated result. Indexed aliases remain searchable. Old empty query
  cache entries do not suppress the revised adapters.
* Sources returning unrelated popular entries no longer pass them as matches.
  Failed extensions with an existing same-host HTML adapter can use that adapter.
* MangaDex at-home URLs strip a trailing slash before appending `/data/...`.
  Old saved bridge page URLs can recover through that same native chapter.

## Real server checks, not mocked reader claims

All checks used SSH on Oracle. No interactive browser or local-PC bridge was used.

* HentaiLib: exact Russian title found in ~1 s, including English/Korean aliases;
  103 chapter records. The anonymous chapter request still returns HTTP 404.
* MangaDex: the same work found by the Russian query in ~1 s; 65 English chapter
  entries. First chapter: 24 original pages; a 60,919,869-byte CBZ downloaded on
  Oracle with 24 image entries and clean ZIP CRC. This is actual network download.
* MangaDex currently lists the original language as Korean but does not list
  Korean chapters for this work. Original language is not chapter availability.
* HentaiLib chapter tested against api.cdnlibs.org, hapi.hentaicdn.org,
  api2.mangalib.me and api.imglib.info; desktop headers, correct site ID and
  published branch variants did not yield an anonymous page response. No account
  credentials, shared tokens or cookies were installed. This reading limitation
  is unresolved under the requested anonymous-only constraint.
* AllHentai cached chapter 1 points to `/belyi_kit/vol1/1?mtr=true`. Its public
  endpoint also returned HTTP 404; the extension reports HTTP 500. This is not
  reported as successful reading. Other source probes are not evidence of a
  fully passing 1,600-source audit.

Compared current Keiyoushi LibGroup/AllHentai sources, Otaku-Melons/mangalib,
aeviww/lib-downloader and redcatpet/mangayomi-ru-sources. They use the same public
chapter API; some explicitly support optional tokens for restricted content.
Sources:
https://github.com/keiyoushi/extensions-source/blob/main/lib-multisrc/libgroup/src/eu/kanade/tachiyomi/multisrc/libgroup/LibGroup.kt
https://github.com/aeviww/lib-downloader/blob/main/providers/hentailib.py
https://github.com/redcatpet/mangayomi-ru-sources/blob/main/sources/ru/manga/hentailib/hentailib.js

Regression tests use explicit provider fixtures for site headers, same-source
chapter mapping, rating feeds, URL joining, verified aliases, query requeue and
frontend source merging. Actual network evidence is separate from these tests.
