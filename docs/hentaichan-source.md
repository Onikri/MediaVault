# HentaiChan

Native manga source, Russian, marked adult/18+. Source id: 990000000000000001.
The existing source selector and global manga discovery include it without
installing an Android/Suwayomi extension. Supported confirmed hosts:
`hentaichan.live` and its published mirror `x17.h-chan.me`.

The adapter supports title search, /manga/ metadata, paginated /related/ chapter
lists, /online/ readers, original fullimg page URLs, previews through existing
reader endpoints, device CBZ export and the existing encrypted Drive import.
Chapter readers are fetched on selection; the entire series is not downloaded
while listing its chapters. Recommendation pages labelled “Похожая манга” are
never used as chapter lists. Redirects outside the confirmed sites are rejected;
inline data is decoded as JSON/Python literals without executing JavaScript.

Adapted from otaku-melons/HentaiChanParser by DUB1401, Apache-2.0, commit
92d80387f6a24fd48c6be0097bbd2d1450353751. Attribution and full license are in
THIRD_PARTY.md and licenses/hentaichan-parser.txt. Its CLI, OS shutdown commands,
extra dictionary/image dependencies and bulk catalogue crawler are not executed.

Validation: six dedicated parser/discovery/CBZ tests use neutral HTML and a tiny
PNG; 23 discovery, five inspection and five manga import tests cover integration.
Live Oracle checks found search results and fetched a real reader's page list
(without downloading/displaying its images). Counts vary as the upstream catalogue
changes. CBZ bytes and Drive encryption use fixtures, not a live content download.
No ML inference is involved in these checks.
