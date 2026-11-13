# Private global content management

Open **Profile → Control center → Управление контентом** as the site owner.
The same private policy governs movies, TV series, anime, manga/manhwa/manhua,
ranobe and books. Repository JSON is an installation default, not the live
administration surface. GitHub commits never replace the owner's runtime rules.

The graphical editor supports bulk pasting source labels (one per line), adding
or deleting any rule, changing its display name and category, multilingual
aliases, source-specific aliases, and editable word/phrase/prefix exclusions.
All choices are editable. There is no second hidden tag exclusion list.
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

New/changed rules queue bounded public metadata discovery. AniList's actual
genre/tag vocabulary is consulted for anime, manga and ranobe; book subject
search uses Open Library; movie/TV catalogue batches use Kinobox. The 18 manga
domains use public LibGroup constants/genre filters or exact tag-cloud links on
approved hosts. Known approved mirrors share source-specific aliases. Requests
are bounded and sequential; the LibGroup gateway uses HTTP/2 with site/referrer
headers. Robots and upstream availability are respected. No images are fetched.
The UI shows matches, source availability and first-batch limits. It does not
claim that closed/unavailable sites were indexed or that a bounded batch covers
an entire source. Ordinary discovery continues adding source-provided metadata.

Exact normalized spelling and declared aliases match automatically. Similar
spellings are suggestions in the private vocabulary search; the owner chooses
semantic merges, rather than an algorithm silently changing site policy.

Validation uses neutral fixtures, private API authorization/conflict/rollback
tests, all-media deletion/restoration/category tests and a responsive graphical
editor contract. These checks do not access adult reader pages or perform ML
inference.
