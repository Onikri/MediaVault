# Static manga taxonomy: GitHub Actions → frontend

This feature publishes a standalone tag index so MediaVault's frontend can
display searchable source tags **before the backend is connected**.

## Paths

- Action: .github/workflows/manga-tags.yml
- Generator: scripts/sync-manga-tags.py
- Static output: public/data/manga-tags.json (bundled by Vite into dist/data/)
- UI: src/MangaStaticTags.jsx embedded in MangaSourceManager
- Tests: tests/test_manga_tag_snapshot.py

## Automatic refresh

The workflow runs on the first push to its branch, supports manual
workflow_dispatch on the default branch, and is scheduled every Monday at
03:23 UTC **after merge to main** (GitHub schedules only the default branch).
It fetches at most one public HTML taxonomy page per supported domain or one
bounded LibGroup constants response per site. Robots rules are checked, time
and size limits apply, redirects are restricted to explicit trusted hosts, and
no login/cookies/JS/CAPTCHA or page images are used.

It commits only public/data/manga-tags.json if it changes. On main, it then
requests a normal pages.yml workflow_dispatch to re-build GitHub Pages.
This requires the repository's GitHub Actions token to have contents:write and
actions:write and branch protection to permit the data commit. If protected
branches reject bot pushes, configure an approved automation identity or
switch the job to a PR-based update, rather than disabling protection.

## Output schema v1

- schemaVersion and generatedAt
- scope = public_taxonomy_only, coverageGuaranteed = false
- sources: exactly 18 requested domain statuses (name, state, tagsFound,
  reason). States complete/partial/stale/unavailable/closed/pending.
- tags: normalized search key, category (tag/genre), display label, original
  labels, and exact contributing source domain names.

Labels remain attributed to their sources. Explicit taxonomy arrays from
LibGroup are filtered to site IDs 1, 2 and 4 respectively. HTML catalogues
are **always marked partial**, even when a filter panel lists many tags;
absence of pagination guarantees or a documented complete taxonomy prevents
calling them complete. A blocked or unreachable site keeps its prior known
tag labels as stale rather than silently dropping them.

The public snapshot is for autocomplete and filters only. It does not claim
that any manga exists for a specific tag; those results still require the
backend /manga/catalog or discovery. Adult source tags do not verify
participants' ages or licensing; the public snapshot deliberately excludes
explicit underage-sexual classifications and does not perform age inference.

## Verification

    python -m pip install requests beautifulsoup4
    python -m unittest discover -s tests -p 'test_manga_tag_snapshot.py'
    python scripts/sync-manga-tags.py --output public/data/manga-tags.json
    npm run build

Before accepting the PR check the refresh job output: a successful workflow
does **not** mean all 18 websites answered. Read each source status and count,
and expand adapters for missing taxonomy pages only when their public structure
and permission can be confirmed. Do not advertise placeholder/empty data as
full coverage.
