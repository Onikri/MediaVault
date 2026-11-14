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

- Running `mediavault-importer:tags-95fddbb59e27`, revision label
  `95fddbb59e27cc1089e678ed370899ceddc7bc61` (= `main` at deploy time). It is the
  previous `p6-43070026350d` image plus `server/manga_catalog_index.py` and
  `server/api.py` from that commit (cached manga tag facets). The Alloha VOD
  cache settings come from the chained `release-p6-*.yaml` override and are
  unchanged.
- Deployed by Claude Code at 12:59 UTC with the lock; backup in
  `/opt/mediavault-backups/tags-95fddbb59e27-20261114T125821Z`.
- Set the revision label to the deployed `main` SHA on every build
  (`--label org.opencontainers.image.revision=<sha>`); a derived image otherwise
  inherits its base's label.
