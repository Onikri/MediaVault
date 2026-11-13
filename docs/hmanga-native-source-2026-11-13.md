# HManga native source (13 November 2026)

This branch adds a native RU/18+ adapter for the public HManga catalogue.
The provided domain hmanga.su redirects to the observed canonical host
hmanga.me. The adapter **does not** alter the reader, Drive encryption,
translation, source ranking, authentication, or frontend.

## Integration

- server/manga_hmanga.py: public Madara-style title search, title/chapter
  inspection, tags, alternate titles, language and format metadata, and
  on-demand extraction of image URLs from the selected chapter's HTML.
- server/manga_sources.py: new source family, dispatch to the adapter.
- server/manga_discovery.py: visible in the native source list and global
  metadata search using the existing job queue.
- server/manga_download.py: chapter import routes through the adapter's
  inspected pages instead of generic page selectors.
- tests/test_manga_hmanga.py: neutral fixture tests, without real adult images.

## Verified versus unverified

The public site was observed serving a WordPress/Madara catalogue with
the path /?post_type=wp-manga&s= and public title/chapter URLs shaped as
/manga/<slug>/ and /manga/<slug>/<chapter>/ on 13 November 2026.
Site content and chapter-image bytes **were not downloaded in this change**.
Offline unit fixtures test the parser contract; they do not prove live chapter
availability on the Oracle machine. The existing /manga/summary
verifyPages workflow remains the source of truth before a reader is enabled.

The chapter list is deliberately marked truncated if only Read First /
Read Last links are exposed. An empty list is reported as unavailable
rather than inventing chapters. Redirects to unrecognized hosts and
other manga titles are rejected. The adapter does not request logged-in
pages, bypass protections, or use undocumented APIs.

## Local checks

    python -m unittest tests.test_manga_hmanga

If that unittest module import style is unavailable in the current checkout,
use:

    python -m unittest discover -s tests -p 'test_manga_hmanga.py'

Also run the existing integration checks before merge:

    python -m unittest discover -s tests -p 'test_manga_discovery.py'
    python -m unittest discover -s tests -p 'test_manga_inspection.py'
    python -m unittest discover -s tests -p 'test_manga_readability.py'
    python -m unittest discover -s tests -p 'test_manga_import.py'

## Live acceptance criteria (Oracle)

1. Query HManga by a non-explicit title in the existing source search.
2. Select a matching result and inspect its published chapter list.
3. Request /manga/summary with verifyPages=true; the checked image must
   actually decode before the existing reader is enabled.
4. Confirm that another title's chapter link and paid/login responses fail
   closed, and verify that the frontend's existing reader remains unchanged.

HManga is the only newly implemented source in this branch. Other requested
sites remain in their existing adapter/Suwayomi states or unverified; do not
advertise them as newly supported based on this PR.
