# Server deploys: Codex and Claude Code

Both agents deploy the importer on the Oracle VM (`oracle-importer-1`). These
rules keep one of us from silently undoing the other.

- `origin/main` is the single source of server code. Merge `server/` changes
  into `main` before deploying, or right after, in the same session. Never build
  an image from a branch whose `server/` differs from `main` without merging it.
- Before building or restarting the importer, check what is running:
  `docker inspect oracle-importer-1` (image, `org.opencontainers.image.revision`
  label) and the newest `deploy/oracle/release-*.yaml`.
- Take the lock file `/opt/mediavault/deploy.lock` (name, time, purpose) before
  a build or restart. If another agent holds it, wait. Remove it once health
  checks pass.
- Derived images (`FROM` the running image + `COPY server/`) start from the
  current running image, so they keep what is already live.

## State on 2026-11-14

- Running `mediavault-importer:facets-734e356457c1`, revision label
  `734e356457c1f52fedcbf5e34af9e46cad748708` (= `main` at deploy time): the
  `p6-43070026350d` image plus `server/api.py` and
  `server/manga_catalog_index.py` from `main` (manga tag facets cached in
  memory and in `DATA_DIR/manga-tag-facets.json`). The Alloha VOD cache
  settings come from the chained `release-p6-*.yaml` override, unchanged.
- Deployed by Claude Code at 13:31 UTC with the lock; backup in
  `/opt/mediavault-backups/facets-734e356457c1-20261114T133141Z`.
- Set the revision label to the deployed `main` SHA on every build
  (`--label org.opencontainers.image.revision=<sha>`); a derived image otherwise
  inherits its base's label.

## Signed library filters release — 2026-11-14

- Codex deployed `mediavault-importer:library-cafc50f769c9`, revision
  `cafc50f769c9d13b6b64e68a45e84f1fa4e56767`, derived from the actual running
  `facets-734e356457c1` image under `/opt/mediavault/deploy.lock`.
- Backup: `/opt/mediavault-backups/library-cafc50f769c9-20261114T171710Z`.
  All 27,909 existing catalogue job IDs survived; cursors were retained or
  advanced by workers. Private settings, service key, policy and environment
  matched the frozen pre-restart state. The shared lock was released after health.
- All 168 server files match the deployed main revision after newline normalization.
  Live signed-filter checks passed, including OR genres, genre AND tag,
  exclusions, separate webtoon mode, and book results without tags. Alloha
  capabilities and the existing compose override chain remain enabled.
- Shared public vocabulary: 181,481 JSON bytes / 1,748 entries versus
  4,165,412 bytes / 36,581 entries before this release. Ordinary-book cleanup
  resumes over derived data in short background transactions; source facts,
  titles and crawl jobs remain intact. The public policy exporter may append
  generated taxonomy snapshot commits without requiring a server restart.
- PR #53 validation: 467 Node tests, 1,000 Python tests, production build and
  all CI UI contracts passed; 116 focused Linux contracts also passed in an
  isolated Oracle container. No interactive browser or subagent was used.

## Source-derived genre release — 2026-11-14

- Codex deployed `mediavault-importer:hentai-ad6a9446341b`, main revision
  `ad6a9446341b09f9b6567da2dec92a99fc4b9785`, derived from the running
  `library-cafc50f769c9` image under the shared deployment lock.
- Backup: `/opt/mediavault-backups/hentai-ad6a9446341b-20261114T184604Z`.
  All 28,014 prior job IDs survived; cursors were retained/advanced, private
  settings/key/policy/environment were unchanged. Alloha health remained enabled.
- All 168 server files matched the deployed revision after newline normalization.
  Live selection found 78,924 Hentai works, including 32,004 from HentaiLib.
  The intersection with explicit non-hentai works was zero. Positive and vetoed
  title endpoints and the client filter/profile projection passed. Existing
  book-cleanup markers remain done; the catalogue queue continues.
- PR #54: 471 Node tests, 1,008 Python tests, production build and full CI passed.
  An isolated Oracle container passed 124 focused contracts. A real-index copy
  verified the derived indexes and their query plans; rollback to the older
  image was tested with removal of only the new custom-function indexes.
- No source crawl was restarted. This release classifies existing and incoming
  catalogue records; it does not assert full coverage of every upstream website.

## Catalogue and Hanime recovery release — 2026-11-14

- Deployed `mediavault-importer:recovery-654cf86742ba`, main revision
  `654cf86742ba14294ee602324a8ac1c3da5f4560`, derived from the running
  `hentai-ad6a9446341b` image under the shared lock. Backup:
  `/opt/mediavault-backups/recovery-r2-654cf86742ba-20261114T210331Z`.
- The first attempt rolled back on an overly strict queue-ID assertion. The
  indexer legitimately deletes completed detail jobs. Verification now permits
  this only when that exact source row has a persisted inspection timestamp
  after restart; missing unfinished jobs and cursor resets still fail the check.
  The second attempt retained unfinished work and verified three completed jobs.
  Private settings/key/policy/environment and all 168 server sources were checked.
- Live `/online` checks passed for both Hitou Meguri Kakure Yu - Mao Hen episodes:
  preparation 200, fragments 206 with video/mp2t and Range, 16-byte AES keys and
  valid MPEG-TS sync after a 2-KB decrypted probe. No video was rendered or saved.
  Catalogue browsing, Naruto and White Whale searches returned data successfully.
- The site build/deploy passed (43640427567), as did full PR #55 CI (43639743001).
  New UI contracts cover stable 28-card paging at 1798px, retained indexed cards
  across outages, bounded retries and stale-error clearing. Alloha and Hentai
  source-genre matching remain enabled; the catalogue queue continues.

## First-page catalogue serialization correction — 2026-11-14

- PR #56, site revision `f2d48058660a9eaa01984fc9291a8878650b16e4`, fixes
  `offset=` on the first manga page. The shared serializer now preserves zero.
  The earlier live diagnostic supplied parameters manually and the layout
  fixture accepted empty integers; both paths now check client-generated values.
- Public Oracle checks reproduced 422 for the old query and 200 with cards for
  fixed first-page limits 24/28, page two, Naruto search and a genre selection.
  The published asset `main-CdMU7Qu-.js` matches Pages run 43643471409 and was
  inspected for the corrected serializer. 472 local Node tests, seven focused
  Python contracts and the production build passed.
- No server image, private settings, queue or indexed data changed. The importer
  remains revision `654cf86742ba14294ee602324a8ac1c3da5f4560`; no restart or
  deployment lock was needed for this client-only release.
- PR CI run 43643432662 passed server/queue validation and the source catalogue
  UI suite, including strict integer query validation. The broader playback/UI
  audit continues independently of the successful client publication.
