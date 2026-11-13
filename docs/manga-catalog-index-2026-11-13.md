# Persistent manga catalogue and source taxonomy — 2026-11-13

This is an incremental catalogue extension for the **existing** MediaVault backend.
It does not replace the React MangaReader, reader routing, encrypted Drive,
native adapters, or Suwayomi server.

## Indexed data

server/manga_catalog_index.py creates persistent catalog_titles and
catalog_tags SQLite tables inside the existing manga-discovery.sqlite.
These tables are **not** subject to the legacy 7-day discovery cache pruning.
The unique key is (provider, public source URL): different providers remain
distinct records. The original tag/genre labels are stored unchanged alongside
normalized search keys, including a small set of unambiguous RU/EN synonyms.

Rows contain only publicly returned metadata: title, alternate names, source,
format, language, cover URL, tags, genres, chapter count where confirmed, and
timestamps. **No chapter images, page bytes, login cookies or Drive data**.

Successful global discovery searches update the persistent index. A title
inspection also enriches the same row with available source tags/genres and
chapter totals. An index write failure must not break the actual reader.

### Taxonomy extraction

- MangaDex: explicit API tag relationships and their localized names.
- MangaLib / HentaiLib / SlashLib: explicit LibGroup genres/tags detail fields.
- HentaiChan, HentaiChan.cc, MangaChan and similar public HTML sources:
  published tag/genre links on search cards and inspected title pages.
- HManga: labelled tag and genre fields.
- Suwayomi: published genre/genres and tags fields when present, with native
  inspection still preferred for sources already handled directly.

If tags are absent, the catalogue marks them as not requested or not provided
in the detail. It never invents tags. The 18-domain source overview continues
to distinguish native, extension, partial mirror, unverified and closed sites.

## Owner-only API

GET /manga/catalog?q=&tag=&provider=&format=&offset=0&limit=30
: browse/search discovered metadata with normalized tag filters.

GET /manga/catalog/tags?provider=&sourceId=&limit=100
: original tags/genres with indexed title counts.

GET /manga/catalog/stats
: per-provider catalogue size and title-with-tags counts.

GET /manga/catalog/{catalog_id}
: one indexed metadata record.

POST /manga/catalog/backfill with {"offset":0,"limit":250}
: copy a bounded page of already discovered source results into the permanent
  index, with nextOffset for pagination. No extra upstream requests.

POST /manga/catalog/enrich with {"ids":["..."]}
: inspect at most three explicit indexed source titles or up to two untagged
  titles on an empty request, using the existing bounded inspection cache.
  No media bytes are downloaded.

The existing /manga/search, /discovery/manga/search, /manga/inspect,
/manga/summary and the React MangaReader keep their contracts.

## Coverage and boundaries

This is **incremental** indexing, not a claim to have crawled every page on
all 18 upstream sites. Sources without verified adapters/extensions cannot
supply tags. Closed, login-only, paid or CAPTCHA-gated material is not bypassed.
Rights and source restrictions must be respected. Adult age labels supplied by
websites are not proof of the depicted characters' or participants' ages;
publishing a catalogue requires separate moderation.

## Tests

    python -m unittest discover -s tests -p 'test_manga_catalog_index.py'
    python -m unittest discover -s tests -p 'test_manga_discovery.py'
    python -m unittest discover -s tests -p 'test_manga_catalog_adapters.py'
    python -m unittest discover -s tests -p 'test_manga_hmanga.py'

Fixtures are neutral. These repository tests and live Oracle source checks
have not been executed in this tool environment. Keep the PR draft until
they pass.
