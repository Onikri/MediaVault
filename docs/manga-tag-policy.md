# Editing manga tags on GitHub

Edit **`server/manga-tag-policy.json`** on `main` and commit. This is the single
editable definition for all manga source adapters, source vocabulary collection,
Oracle indexing, title profiles, catalogue cards and filter options.

Each `tags` entry has a stable `key`, a display `label`, and `aliases` containing
the actual source labels in any language. Matching normalizes case, punctuation,
Unicode width and ё/е; it does not guess unrelated words. For example:

```json
{"key":"экология","label":"Экология","aliases":["Ecology","Экология"]}
```

Keep `key` unchanged to rename the display label. An optional `sourceAliases`
object maps source domains to additional source-specific labels. Those aliases
do not apply to other sites. The ordinary aliases apply uniformly to all 18
registered sources and the other manga adapters.

Delete the entry to remove the tag from both genres/tags, index facets, cards and
filter controls. `excludedTerms` and `excludedPrefixes` provide shared exclusions:
an exclusion matching any alias hides that canonical tag across its languages.
These lists contain plain terms, not executable regex or code.

The **Validate and apply manga tag rules** workflow checks the JSON, alias
ambiguity, indexing, deletion/restoration and deployment authentication. A failed
validation preserves the active version. A successful main commit sends a signed,
scoped request to Oracle. Oracle verifies the current committed configuration,
transactionally rebuilds its tag projection, and publishes the new revision.
There is no VM restart or account-session transfer for a rule edit. Concurrent
outdated updates are rejected. The browser refreshes the policy on focus and
every minute; already cached metadata is projected through the current rules.

Source-provided facts are retained privately so additions and restored aliases
can match already collected metadata without a new scrape. This does not invent
tags, fetch missing pages, or perform an exhaustive catalogue crawl. Titles/facts
not collected yet are added by normal discovery and title inspection. Sources
that do not supply the tag remain untagged; unavailable sources retain their
availability status. The static vocabulary is a generated view and should not be
edited manually.

The one-time server installation provisions `MANGA_TAG_DEPLOY_KEY` as a repository
secret and `/data/manga-tags-deploy.key` on Oracle. The key authorizes only this
configuration endpoint. The public Oracle origin is the `MANGA_ORACLE_URL`
repository variable. No account cookies, SSH private keys, or model credentials
are committed or sent in the policy. Initial code upgrades still use the normal
server release procedure; the automatic deployment here is scoped to tag rules.

Validation uses neutral multilingual tag fixtures across the 18 source domains;
it makes no upstream image requests and performs no ML inference.
