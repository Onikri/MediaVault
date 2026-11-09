# Reader roles: the director and parallel workers (2026-11-09)

## What changed

| | Before (v59) | Now (v60) |
|---|---|---|
| Chapter split | 120 segments a request | Parts of ~7500 characters at paragraph borders; a ~2600-character part at the reading position goes first |
| Keys | One request per key, at least 4 s apart per project. A personal key replaced all three server keys | Each request goes to the least busy key (2 in flight per key) within that model's budgets. A personal key joins the server keys |
| Budgets | 15 RPM | Per model: RPM, input TPM (estimated from the body before sending) and requests per Pacific day. A Google `QuotaFailure.quotaValue` replaces the default |
| Worker answer | JSON object per segment, narration included (~40 output tokens a segment) | `номер\|вид\|кто\|эмоция\|сила` only for speech and thoughts, plus a few mood ranges (~5 tokens a segment) |
| Thinking | Model default | `LOW` for workers and for the book card |
| Overload or refusal | The whole chapter fell back to the heuristic | 5xx moves to another key, then 3.1 Flash Lite. A refused part is halved twice, so only the refused paragraph stays untagged |
| Characters | Book card once; workers' new names were dropped | The director merges new speakers into the card after each chapter: an alias of a known character, or a new card with a voice description and a Gemini voice |
| Reuse | In-memory map, lost on reload | IndexedDB per chapter text; the next chapter is prepared in the background |
| Playback | New roles restarted the current paragraph | The phrase being read continues; only later phrases change |

Defaults in `server/google_gateway_limits.py` (`BUDGETS`) are server policy. Google does not publish the remaining quota.

## Real inference (live, Gemini 3.5 Flash Lite, three server keys)

### Measured live

Six RanobeHub chapters were measured: «Повелитель тайн» 3–4, «Реинкарнация безработного» LN 1–2 and «Начало после конца» 2–3.

The old prompt was sent straight to Google through the three keys in parallel (`res-baseline`): 7–10 s per chapter (the slowest 120-segment request) and 3000–11600 output tokens. Two of the six chapters got HTTP 503 and fell back to the heuristic.

The new flow ran end to end. The real `src/tts/director.js` called the deployed v60 gateway (`/reader/google/generate` in the importer container) with the same keys. The first chapter of each book started without a card, exactly as in the reader.

| Chapter | First part | Whole chapter* | Parts / requests | Keys used | Tokens in / out |
|---|---|---|---|---|---|
| Повелитель тайн 3 (no card yet) | 1.6 s | 3.1 s | 3 / 4 | 0, 1, 2 | 6120 / 626 |
| Повелитель тайн 4 | 1.2 s | 6.6 s | 3 / 4 | 0, 1, 2 | 7952 / 2350 |
| Реинкарнация 1 (no card yet) | 1.8 s | 8.0 s | 6 / 12 (2 parts refused, split) | 0, 1, 2 | 17933 / 4001 |
| Реинкарнация 2 | 1.1 s | 6.1 s | 5 / 8 (1 refused, split) | 0, 1, 2 | 15307 / 3170 |
| Начало после конца 2 (no card yet) | 1.8 s | 4.5 s | 3 / 5 | 1, 2 | 6762 / 1087 |
| Начало после конца 3 | 1.1 s | 1.2 s | 2 / 2 | 1, 2 | 4080 / 105 |

\* Includes the director's call that adds new speakers to the card. The parts are applied to the text as they arrive.

The book card took 3–4 s on the same model. Reopening a chapter costs no requests (IndexedDB).

### Accuracy against hand labels

Text prefixes were labelled by hand. The labels are in the benchmark script in the session scratchpad.

| | Old prompt | New flow |
|---|---|---|
| «Повелитель тайн» 4: who speaks (33 lines: hero, baker, fortune teller, street vendors) | 23/33 (vendors and the fortune teller unnamed) | 33/33 |
| «Начало после конца» 2: text in quotes that is a book the hero reads, or a page-turn sound, must be read by the narrator (30) | 3/30 | 30/30 |
| Same chapter: the mother's two lines | 2/2 | 2/2 |

`MINIMAL` thinking gave the same speed but marked the book excerpts as the hero's speech. `LOW` fixed that at about +0.2 s a part.

### Refusals and fallbacks (live)

Google refuses some parts of «Реинкарнация безработного» with `promptFeedback.blockReason=PROHIBITED_CONTENT`. 3.5 Flash Lite, 3.1 Flash Lite, Gemma 4 26B and 31B all refuse the same text, so it is not retried on another model. The part is halved instead.

Two fallback candidates were dropped:
- 2.5 Flash Lite answers HTTP 404 on these keys.
- Gemma 4 refuses any `thinkingLevel` (HTTP 400), so `forModel()` removes it for Gemma.

## Mocked tests (no model output)

- `tests/tts-text.test.mjs`:
  - compact answer parsing;
  - nested quotations;
  - part planning;
  - a mocked director run: parts sent in parallel, a refused part halved, a merge into the card, a cached second run.
- `tests/test_google_gateway_limits.py`:
  - least busy key and two in flight per key;
  - RPM, TPM and RPD waits;
  - learned Google quota values;
  - a personal key pooled with server keys;
  - a 503 moving to another key.
- `tests/ranobe-reader-browser.cjs` and the other reader browser tests use mocked Google answers in the new line format.
