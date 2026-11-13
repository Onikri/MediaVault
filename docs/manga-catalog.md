# Persistent source catalogue

The normal manga library reads the Oracle metadata index (API 72), alongside
the existing metadata catalogues and background Suwayomi discovery. It retains
the source's reader URL separately from its canonical title URL. Numeric source
IDs stay strings throughout the client and server.

Title aliases, source/language, format, known year/age, genre and all selected
tags participate in the indexed query. English/Russian tag aliases share
`server/manga_tag_aliases.json` with `src/taxonomy.js`; a test checks parity.
The static vocabulary and live facets retain provider labels and provenance.

Missing facts are enriched on demand from title metadata, with two requests
globally in flight and at most twelve candidates per displayed filter query.
No page images are requested by enrichment. Read-only catalogue routes and
bounded known-ID enrichment use the viewer permission; cache backfill remains
owner-only. Settings, account cookies and chapter contents never enter this index.

The catalogue grows from successful discovery and title inspection. It is not
an exhaustive mirror of every registered source. A source registry entry is not
proof of availability; closed, unverified and unavailable sources remain labeled.
The weekly vocabulary collector observes robots rules, bounded redirects,
response sizes and source-scoped HTTP/2 headers for Lib taxonomy. It retains
previous labels as stale when the source cannot answer. Bot snapshot updates
request a fully validated Pages release; manual audits do not publish by default.

Validation: Node helper/identity tests, Python SQLite/API/adapter tests and the
neutral `manga-catalog-browser.cjs` contract. Browser and HTTP mocks do not
establish availability of an external reader or perform any ML inference.
