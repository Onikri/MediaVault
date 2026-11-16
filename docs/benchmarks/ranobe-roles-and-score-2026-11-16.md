# Ranobe narration: line borders and the sound director (2026-11-16)

Real model inference through the server key pool (`gemini-3.5-flash-lite`,
called with `.codex-local/dev/google-call.py` on the VM). Unit and browser
tests use canned answers; these are the only live numbers.

## Line borders (`scripts/benchmarks/roles-eval.mjs`)

Trap chapter of 24 paragraphs written for the test (dashes inside lines,
author's words without a speech verb, hyphens for dashes, quotes inside a line).

| Pass | Borders and kind | With the speaker |
|---|---|---|
| Punctuation rules (`heuristicRoles`) | 14/24 | 14/24 |
| Workers on atoms, LOW thinking | 23/24 | 23/24 |
| + arbiter on doubtful paragraphs, HIGH thinking, before the quote rule | 23/24 | 23/24 |
| + arbiter after the rule for quotes inside a line | **24/24** | **24/24** |

One run each. The remaining worker miss is paragraph 13 («— Он сказал: «Жди до
утра» — и ушёл, — вспомнила Лена.»): the quotation inside Lena's line went to
the narrator until the prompt named this case. Worker request: 2255 prompt /
875 output tokens; arbiter: 1810 prompt / 253 output / 2537 thinking tokens.

## Sound director (`src/tts/soundtrack.js`)

One request per chapter: the whole chapter (numbered paragraphs) and the
208-piece catalogue (Kevin MacLeod, CC BY 4.0); HIGH thinking.

«Повелитель» (RanobeHub), «Интерлюдия», 91 paragraphs: 12 907 prompt,
145 output, 2 788 thinking tokens. Six scenes: awe after the master leaves →
calm devotion → jealousy with humour → the Albedo–Shalltear quarrel →
an unhurried talk → business-like calm; mysterious, calming, humorous and
relaxed pieces, all at volume 2/5.

«Повелитель», «Эпилог», 92 paragraphs: 13 172 prompt, 140 output, 3 234
thinking tokens. Six scenes: a quiet room (Immersed) → a tense talk (piano
trio) → Albedo's dark obsession (Quinn's Song: A New Man) → the throne room
(The Pyre, 3/5) → triumph (At Launch, 4/5) → sinister resolve (Black Vortex,
4/5). Judged by reading the scenes against the text; no listening test.
