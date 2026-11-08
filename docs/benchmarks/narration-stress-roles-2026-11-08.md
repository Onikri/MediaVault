# Narration: word stress, title bible and role pass — measurements (2026-11-08)

Actual ML inference is listed separately from mocked contract tests.

## Does Supertonic 3 follow a stress mark?

U+0301 is in the model vocabulary (index 146; `ё` becomes `е`+U+0308, index 152).
Single words synthesised with each stress variant (fp32, 5 steps, voices M2/F2); the two
vowel nuclei were measured (duration × energy). The louder/longer nucleus follows the
mark in `а́тлас/атла́с`, `му́ка/мука́`, `у́же/уже́`; without a mark the model reads
`уже` with the stress on the first syllable (wrong). In `замок`, `кружки`, `стрелки` the
simple envelope did not separate the syllables, so those pairs are inconclusive.
Script: `scratchpad stress_probe.py` (not committed), audio in `.codex-local/benchmark/stress-2026-11-08`.

## Stress accuracy on 12 homograph-heavy sentences (actual inference)

| Engine | Correct stressed words | Outputs that changed the text |
|---|---|---|
| RUAccent 1.5.8.3 · turbo3.1 (CPU, 0.12 s per sentence) | 87–88 % | 0 |
| Gemini 3.5 Flash Lite | 76 % | 2 |
| Gemma 4 26B A4B | 65 % | 1 (Latin `á` homoglyphs) |
| Gemma 4 31B | 60 % | 4 (partly free-tier errors) |
| Gemini 3.5 Flash | 65 % | 4 (free tier: 20 requests/day per project; the test used only key slot 1 directly, bypassing the gateway, and spent that slot's quota — slots 2 and 3 still answered) |

One gold label was wrong (`стоя́ли` is correct); RUAccent's remaining misses are the
hardest pairs on purpose (`замо́к/за́мок`, `мука́/му́ка`, `хлопо́к/хло́пок`).
Decision: RUAccent places stresses; Google models do roles and emotions only.

## Title bible and chapter roles on «Война и мир», т. 1, гл. II (actual inference)

- Bible: Gemini 3.5 Flash Lite, 3.7 s. 7 characters with aliases (Анна Павловна /
  Annette; Маленькая княгиня / Лиза / Lise; Пьер / monsieur Pierre; князь Василий; Элен;
  аббат Морио; тётушка), temperament, manner of speech, timbre and pitch, narrator voice and
  a 9-word name lexicon (Безу́хов, Болко́нская, Ипполи́т…). Gemini 3.5 Flash Lite is the
  bible model (the owner does not use non-Lite Flash; no text 3.8 Flash Lite is offered to
  these keys, only `gemini-3.8-flash-lite-tts`); Gemma 4 31B is the fallback on quota/overload.
- Chapter pass: Gemma 4 26B A4B with the bible, 24 s for 32 segments. Speakers correct in
  11 of 14 lines (heuristic alone: about 3); one line given to the wrong speaker
  (князь Василий instead of the little princess), one left unattributed.

## Mocked contract tests (no model output)

`tests/ranobe-reader-browser.cjs` runs real Supertonic synthesis but MOCKS the Google
bible/roles answers and the `/tts/accent` answer; it checks that stressed text reaches the
synthesiser, that names and emotions are drawn in the text and the cast panel shows the
models in use.
