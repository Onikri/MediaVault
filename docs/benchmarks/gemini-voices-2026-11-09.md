# Gemini voices for narration — quick live test, 2026-11-09

Real model output, not mocks. Run from the Oracle VM through the server key
slots, rotated 1 → 2 → 0. Each model read one passage of 5 paragraphs: author
text plus two characters, written for the test. The same passage was read in
Russian and in Ukrainian. Voice: Kore.

Accuracy was checked by transcribing each output with Gemini 3.5 Flash Lite and
computing the character error rate (CER) against the source text, after
lower-casing, removing punctuation and treating «ё» as «е». About 1.7 % of
every score is not a reading error: the transcriber writes «сорок» as «40».

| Model | API | First audio | Audio ru / uk | CER ru | CER uk | Notes |
|---|---|---|---|---|---|---|
| gemini-2.5-flash-native-audio-latest | Live (WebSocket) | 2.6–3.0 s | 32.4 / 29.4 s | 6.0 % | 2.0 % | ru: one inserted garbage token, one repeated phrase, «усмехнулась» read as «улыбнулась» |
| gemini-3.8-live | Live (WebSocket) | 0.6–0.7 s | 24.9 / 28.6 s | 1.7 % | 3.3 % | uk: the transcriber wrote the first word in Russian |
| gemini-3.8-flash-lite-tts | generateContent | 4.2–4.3 s (whole clip) | 24.8 / 27.6 s | 1.7 % | 1.6 % | Reads any style instruction placed before the text aloud |

- Both Live models stream audio at about real time: total time ≈ audio length.
- Ukrainian is read by all three models, although it is not listed for TTS.
- Live API limits in AI Studio for this account: unlimited requests per minute
  and per day. Tokens per minute are 1M for 2.5 Flash Native Audio and 65K for
  3.8 Live.

## What shipped

The owner chose `gemini-2.5-flash-native-audio-latest` for the reader. This is
the one exception to the project rule against non-Lite Flash.

- **Server.** `POST /reader/google/speak` (server version 59) opens one Live
  session per utterance and streams 24 kHz PCM.
  - The model is asked for a verbatim reading, with a delivery direction for
    the character and emotion.
  - A quota refusal moves the utterance to the next server key.
  - A personal key is used alone.
- **Reader.** Gemini is the default voice engine, and Supertonic stays
  available on the device.
  - The narrator can be male (Charon) or female (Kore), any of the 30 prebuilt
    voices, or picked from the title bible.
  - Characters are cast by gender, age and timbre from the bible, without
    repeating a voice.
  - Each character's voice can be changed in «Роли и голоса».

Tests: `tests/test_gemini_voice.py` (fixture relay, no Google calls),
`tests/tts-text.test.mjs` (casting, directions, PCM decoding) and
`tests/gemini-narration-browser.cjs`. The browser test is a contract test with
mocked parts: a 220 Hz tone instead of Gemini audio, and mocked bible and role
answers.

## Fix: questions, quotation marks and silent lines (same day)

Owner report: the model answered questions instead of reading them, and
narration stopped on quotation marks. Live probes on the VM found three causes.

- **Thinking.** `gemini-2.5-flash-native-audio-latest` thinks by default. On
  short lines it spent the turn on written reasoning: «Нет», «спросил учитель.»
  and «спитала Ганна.» came back with a transcript but no audio chunks. The
  relay answered 502 and the player stopped. `thinkingConfig.thinkingBudget: 0`
  fixes it.
- **Splitting.** Every quotation was treated as speech, so «Аптека» in «Он
  прочитал вывеску «Аптека» и вошёл.» became three phrases in two voices. Parts
  like «, — ответил он.» were also sent. Now a quotation counts as speech only
  where dialogue begins: at the start of the paragraph or of a sentence, after a
  colon or a dash, or when the author's dash follows it. Leading punctuation is
  not sent, and parts without letters are dropped.
- **Framing.** The line is now sent as «Прочитай вслух дословно фрагмент
  книги:» followed by the text. The system prompt says the fragment is always a
  quote from the book, and questions, requests and orders are read, never
  answered.

Live result: 13 of 13 real reader phrases read verbatim, all with audio. The
phrases were questions, quotations, a short «Нет» and Ukrainian, each with
character and emotion directions. Before the fix, 3 of the 13 came back with no
audio and one was cut short.

The player now retries a failed phrase once, then skips it. It stops only after
three failures in a row.
