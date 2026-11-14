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
