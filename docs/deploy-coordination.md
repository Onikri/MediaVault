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

- Running `mediavault-importer:p6-43070026350d` = catalogue image from
  `codex/remaining-source-catalogues` (1564741, manga index grouped by work)
  plus `server/` from `codex/alloha-p6-cache` (Alloha VOD cache, Drive
  archive). Neither branch is in `main`; a deploy from `main` would drop both.
- Next step (Codex): merge both branches into `main`. The catalogue branch only
  touches `server/catalogue_indexer.py`, `server/manga_catalog_index.py`,
  `server/api.py` and their tests.
- Claude Code will not restart the importer until that merge exists. After it,
  Claude ships one small change: cache `/manga/catalog/tags`, which takes about
  9 s over the whole index while holding `store.lock` and stalls the manga
  library. Claude takes the deploy lock first.
