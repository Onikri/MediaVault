# MediaVault

Keep task caches, downloaded sources/models, browser profiles, logs and temporary
files in `.codex-local/` inside this checkout on drive D. Dot-source
`scripts/cache-env.ps1` before installing dependencies or running tools on Windows.
Never commit `.codex-local`, credentials, model weights or decrypted manga pages.

The manga reader uses the AGPL Libre Manga Translator sources in `lmt/`.
Preserve upstream attribution and publish corresponding integration source.
MangaJaNai model licensing is recorded in `THIRD_PARTY.md` and the model manifest.
Do not replace neural inference with interpolation while calling it MangaJaNai.

Run relevant Node/Python tests and a production build before proposing changes.
Document actual ML inference separately from mocked API/browser contract tests.
