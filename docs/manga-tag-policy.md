# Private global content management

Open **Profile → Control center → Управление контентом** as the site owner.
The same private policy governs movies, TV series, anime, manga/manhwa/manhua,
ranobe and books. Repository JSON is an installation default, not the live
administration surface. GitHub commits never replace the owner's runtime rules.

The graphical editor supports bulk pasting source labels (one per line), adding
or deleting any rule, changing its display name and category, multilingual
aliases, source-specific aliases, and editable word/phrase/prefix exclusions.
All choices are editable. There is no second hidden tag exclusion list.
Enable **Все найденные теги, кроме исключений** to discover source vocabulary
automatically. Configured rules then provide aliases, labels and category
overrides instead of limiting which tags may exist. Exact hidden tags are also
editable in the exclusions tab; deleting a configured tag retains its spellings
there so discovery cannot silently bring it back. Titles remain in the library
when a tag name is hidden. Removing that exclusion restores retained matches.
Visibility-only edits in automatic mode do not rewrite the entire corpus.
Saving validates aliases and atomically reindexes retained source facts. A stale
editor receives HTTP 409 without overwriting another saved revision. Discarding
unsaved changes leaves Oracle unchanged.

Rules stay in `/data/manga-tag-policy.json` on Oracle (the filename is retained
for compatibility). The file is private, mode 0600. Administrative endpoints
require the existing Google-verified owner session. Guest, share and viewer
roles cannot read the policy, save rules, refresh sources, or contribute shared
index facts. The former signed GitHub update endpoint returns HTTP 410. The
workflow only validates bundled defaults. No Workers account or execution of
uploaded scripts is involved.

Public clients receive only visible matching rules and a digest of that public
projection; hidden entries and exclusion terms are omitted. The private
configuration is never sent to GitHub, browser persistence or public logs.
Public catalogue labels are necessarily visible as part of the catalogue.
Clients refresh rules on focus and every minute, including already open titles
and cached catalogue cards. Tag/genre categorization applies across media kinds.

Source labels are retained independently of the current projection. Adding a
previously unknown alias or restoring a tag immediately matches existing facts.
Owner catalogue browsing also contributes bounded normalized metadata for all
media kinds. Source facts never include account cookies, streams or reader bytes.

Automatic mode starts a durable, metadata-only catalogue crawler on Oracle.
Each source cursor and pending detail request survives server restarts. Two
workers share a per-host throttle, back off on errors and stop ingesting when
less than 512 MB disk space remains. Repeated pages are treated as errors rather
than claiming completion. Source listing pages without tags queue separate
title metadata requests; chapter and image endpoints are never requested.
Cached cards use indexed SQL tag/genre queries and pagination, with no former
10,000-row read ceiling. The library displays ingestion progress and keeps
serving cached cards while the initial full crawl continues. Selecting a known
tag can prioritize its source-provided catalogue route. Unavailable and closed
sources keep explicit statuses and their previously cached cards.

New/changed rules also queue public metadata discovery. AniList's actual
genre/tag vocabulary is consulted for anime, manga and ranobe; book subject
search uses Open Library; movie/TV catalogue batches use Kinobox. The 18 manga
domains use public LibGroup constants/genre filters or exact tag-cloud links on
approved hosts. Known approved mirrors share source-specific aliases. Requests
are bounded and sequential; the LibGroup gateway uses HTTP/2 with site/referrer
headers. Robots and upstream availability are respected. No images are fetched.
The UI shows source availability, actual pages processed and cached counts.
HTTP/2 support requires the `httpx[http2]` dependency, and Lib list requests omit
unsupported detail-only fields. Tags use `tags[]`, genres use `genres[]`.
The initial full catalogue is not instantaneous; successful feeds continue to
their upstream last page and are periodically refreshed. Optional manual-only
mode retains the previous bounded discovery behavior.

Exact normalized spelling and declared aliases match automatically. Similar
spellings are suggestions in the private vocabulary search; the owner chooses
semantic merges, rather than an algorithm silently changing site policy.

Validation uses neutral fixtures, private API authorization/conflict/rollback
tests, all-media deletion/restoration/category tests and a responsive graphical
editor contract. Cursor recreation, repeated-page recovery, automatic vocabulary,
fast exclusion restoration and a real HTTP/2 transport constructor are covered.
Live transport smoke checks use metadata endpoints separately from those
fixtures. These checks do not access adult reader pages or perform ML inference.
