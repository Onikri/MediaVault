# Google Drive: audiobooks and translated manga on the VM (2026-11-13)

The title page's save window (`src/ExportSheet.jsx`) now offers, for Google
Drive, work that keeps running on the Oracle VM with the owner's computer off.

## Ranobe and books: text, audiobook, or both

`src/RanobeExport.jsx` shows «Что сохранить»: Текст / Аудиокнига / Текст и аудио.
The audiobook choices appear only where they work: Russian or Ukrainian text
(the narration prompt in `server/gemini_voice.py`), Gemini voices on the server
(v59+) for the device, and for Drive a server reporting `ranobeDriveAudio`
(v71, `narration-export.html` installed in the image).

The voicing is the reader's own, not a simplified copy:
`src/tts/chapter-script.js` runs the title bible (`studyBook`), the director's
role pass (`analyseChapter`, Gemini 3.5 Flash Lite or Gemma 4 through the
server key pool), the cast with the listener's voice choices
(`castVoices` → `geminiCast`) and `geminiRows`. `Narration.jsx` shares its
preferences with it.

- **Device**: chapters are read and voiced one at a time in the browser with
  `chapterAudio` and `audiobookWriter`; every chapter is its own Ogg Opus file.
  Stopping keeps the finished chapters.
- **Drive**: the job carries `output` and `voice` (the reader's narrator,
  pace, role/bible models, saved voice choices, cast and bible for this book).
  For every chapter the worker:
  1. loads the text (`run_import.chapter_text`, the reader's adapters),
  2. runs the **unchanged** director in headless Chromium
     (`server/narration_runtime.py` → `dist/narration-export.html`, Google only
     through the owner's `/reader/google/generate`, every other request
     aborted, one persistent profile per owner so the bible and roles carry over
     between chapters),
  3. voices each row in its own voice with Gemini 2.5 Flash Native Audio
     (`server/ranobe_audiobook.py`, server keys in rotation; silent short lines
     go to the 3.8 Flash TTS model, as in the reader),
  4. encodes Ogg Opus (ffmpeg/libopus, 48 kbit/s), encrypts it and writes it to
     Drive next to the text (`.opus`, `audio/ogg`, category `book`).

  Text and audio have separate fingerprints: a chapter whose text is already in
  Drive gets only its audio. Another narrator, pace, model or voice choice is
  another audiobook; a bible that grew while the book was voiced is not.
  Voiced phrases stay AES-GCM sealed on the VM (`.codex-local/audiobook-phrases`,
  ≤384 MB, 7 days) until the chapter is written. When every key is out of quota
  (voice, or the whole role pass failed), the task goes back to the queue with
  `resumeAt` (2 min, doubling up to 1 h) instead of failing.

The library plays these files: `MediaViewer.jsx` opens `book` items with an
audio MIME type in the audio player instead of the text reader.

## Manga with translation to Drive

`src/MangaImport.jsx` (sheet mode) enables «С переводом» for Drive when the
server reports `mangaDriveTranslation`. The job carries `render` (the reader's
translation settings, validated by `manga_export.Translation`); the worker
translates each chapter with `manga_export.produce` (the same renderer and
encrypted page cache as device exports, `translate_pages` in headless
Chromium), then encrypts the CBZ into Drive as its own translation
«Перевод MediaVault» next to the original.

## Not done

A separate subtitle track in the video save window: the import pipeline writes
one MP4 per episode and has no sidecar subtitle files yet, so the option is not
offered.

## Tests

Mocked contracts (no real model or voice inference):

- `tests/test_drive_audiobook.py`: key rotation, quota pause, silent lines, the
  sealed phrase cache and resume, text + audio fingerprints, multi-voice rows,
  job validation, translated manga encrypted into Drive, the `resumeAt` queue.
- `tests/ranobe-audiobook.test.mjs`: `chapterScript` runs the real director
  with mocked Google answers; the narrator and each hero get their own voices;
  per-chapter files, stopping, a failed role pass.
- `tests/narration-export-browser.cjs`: the built VM page in Chromium, bound
  like `narration_runtime.py`.
- `tests/ranobe-export-browser.cjs`, `tests/manga-drive-translation-browser.cjs`:
  the save windows offer only what the server supports and send the expected
  jobs; the device audiobook writes real Opus files (mocked tone instead of speech).

## Real inference

See the section «Live check on the VM» below; it is recorded after deployment.
