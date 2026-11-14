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
