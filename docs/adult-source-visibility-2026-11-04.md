# Adult and multilingual source visibility — 2026-11-04

The VM already has HentaiLib, AllHentai and HenChan extensions installed. Live bounded catalogue checks returned60 entries for HentaiLib and50 for AllHentai; HenChan timed out. These checks establish catalogue response, not universal chapter/image availability. No catalogue titles or page images were logged or persisted by these checks.

Added a source-metadata-based18+ filter in the source selector and installed-extension manager. The manager continues to distinguish installation from source health. Multilingual labels are explicit. The discovery source list and queue previously excluded every Suwayomi source whose language was `all`; these are now available when the user selects all languages, without silently adding them to a language-specific search. Alias preparation accepts multilingual sources too. Authentication and private extension preferences remain on the VM.

Validation:23 Python discovery/SQLite queue tests, including a multilingual source selected by id and title aliases; actual React source selector/extension manager with fixture API responses; production build. No ML inference changes. The earlier rating/showcase release was confirmed live by matching both public asset hashes before this update.
