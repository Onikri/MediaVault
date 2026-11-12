# Title metadata and ordinary Russian manga search, 2026-11-12

The online title page discarded aliases, chapter/volume totals and the number of aired episodes when it constructed its display profile. An asynchronously loaded Russian dossier was also not forwarded to source discovery. A failed source identity check stayed cached under the unchanged title ID.

The shared title detail helpers now preserve these fields. Catalogue aliases appear below the title and reach discovery and inspection. Adding dossier aliases retries failed checks without restarting an open reader. External-ID, publication-year and work-name matching remain unchanged; this change does not accept unrelated search results.

Ongoing anime distinguishes aired episodes from the planned total. Manga distinguishes the catalogue total from the selected source's chapter count and latest chapter number. Source counters appear after the existing image-readability check; duplicate translations of the same volume/chapter are counted once, fractional chapters are retained and truncated lists are labelled as lower bounds. Unknown values are not invented. Kitsu/AniList publishing statuses now map to Russian.

## Verification

- 24 targeted Node tests passed, covering catalogue metadata, identities, progressive profiles and franchise seasons. Three existing Python title identity tests passed.
- Browser contracts passed at 390 and 1440 px, including an initially rejected inspection that becomes valid when its Russian alias arrives. These use fixture API replies, not live provider availability.
- Production build passed, including the AGPL LMT build. Built title geometry passed at 390, 1440, 1920 and 3440 px.
- Live check on Oracle: MangaLib search for `Yotsuba` returned the Russian work `Ёцуба и!`, its original aliases and chapter URL. Title inspection returned 113 chapter/translation entries (not a deduplicated count). The existing readability verifier fetched and accepted a real image from volume 1, chapter 1. No reader page bytes or account credentials were stored or committed.
- The broader pre-existing showcase browser test has an ambiguous heading selector and, after narrowing that selector in a temporary copy, fails its mobile navbar stacking assertion. The same assertion also fails against the unchanged previous build. This is not reported as a passing test or as a navbar fix; the separate geometry check covers only this change's title layout.

No ML inference or Google translation performance was exercised in this task. No backend parser, source credentials, proxy or regional-access settings were changed. This is not an audit or restoration of every Russian provider; pornographic catalogue access was outside the implemented scope.
