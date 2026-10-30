# Использованные открытые библиотеки

Собственные компоненты MediaVault вызывают эти библиотеки; платные сервисы не подключены. Метаданные и публичные playback API отделены от Google Drive.

| Библиотека | Назначение | Лицензия / исходники |
|---|---|---|
| React / React DOM | Интерфейс | MIT · https://github.com/facebook/react |
| Radix UI | Доступные диалоги и вкладки | MIT · https://github.com/radix-ui/primitives |
| Motion | Анимации с учётом reduced motion | MIT · https://github.com/motiondivision/motion |
| Lucide | Иконки | ISC · https://github.com/lucide-icons/lucide |
| Vite | Сборка | MIT · https://github.com/vitejs/vite |
| anime-dl-core 0.5.1 | Плееры Kodik/Aniboom/Sibnet/Animedia/CVH/VK/AniLiberty; публичные playback API разрешены точным списком | MIT · https://github.com/ialakey/anime-dl-core |
| m3u8 6.0.0 | Разбор HLS | MIT · https://github.com/globocom/m3u8 |
| requests | HTTP источников | Apache-2.0 · https://github.com/psf/requests |
| cryptography | Совместимое с Web Crypto AES-GCM | Apache-2.0/BSD · https://github.com/pyca/cryptography |
| google-api-python-client / google-auth | Авторизованный Drive владельца | Apache-2.0 · https://github.com/googleapis/google-api-python-client |
| FFmpeg | Локальная сборка и проверка MP4 в Colab | LGPL/GPL зависит от сборки · https://ffmpeg.org/legal.html |
| JSZip 3.10.1 | CBZ/ZIP | MIT/GPLv3 · https://github.com/Stuk/jszip |
| EPUB.js 0.3.93 | Книги EPUB | BSD-2-Clause · https://github.com/futurepress/epub.js |

`anime-dl-core` устанавливается как пакет, не копируется в проект. Его игроки используют переданный клиент HTTP, чтобы не передавать Google-токены источникам и не обращаться к API-каталогам. Оригинальная лицензия:

```text
MIT License

Copyright (c) 2026 ialakey

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## React

```text
MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

```

## Radix UI

```text
MIT License

Copyright (c) 2022 WorkOS

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

```

## Motion

```text
The MIT License (MIT)

Copyright (c) 2024 [Motion](https://motion.dev) B.V.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

```

## Lucide

```text
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

```


## FSRCNN ×2 / ONNX Runtime Web (optional neural super-resolution)

- Inference runtime: [Microsoft ONNX Runtime Web 1.30.0](https://github.com/microsoft/onnxruntime), MIT license, loaded on demand from jsDelivr.
- Pretrained model: [televisualarts-cloud/wefax_decoder, fsrcnn_x2.onnx](https://github.com/televisualarts-cloud/wefax_decoder/blob/main/wefax/models/fsrcnn_x2.onnx), converted from [Saafke/FSRCNN_Tensorflow](https://github.com/Saafke/FSRCNN_Tensorflow), Apache-2.0 license as published by the model distributor ([full FSRCNN license](https://github.com/televisualarts-cloud/wefax_decoder/blob/main/wefax/models/FSRCNN_LICENSE.txt)).
- Size: 35,054 bytes. Git blob SHA-1 verification: 0ce756653b71056586ab508710135f4a3c967214. Invalid weights are rejected. This model is not a postprocessing shader. The source video is not sent to a remote inference server.
- ONNX Runtime Web is copyright Microsoft Corporation and licensed under MIT: https://github.com/microsoft/onnxruntime/blob/main/LICENSE.
- Neither the pretrained model nor the ONNX Runtime Web package is committed as part of this source tree; they load on demand from the listed public sources. The model and JS/WASM binaries are third-party network dependencies and won't be available offline unless previously cached by the browser.


## Anime4K / Anime4K.js

- Algorithms: [bloc97/Anime4K](https://github.com/bloc97/Anime4K), MIT.
- Browser WebGL port: [monyone/Anime4K.js](https://github.com/monyone/Anime4K.js), `anime4k.js` 1.1.3, MIT, Copyright (c) 2023 もにょ～ん. Full license is included in the npm distribution. The app bundles the selected shader profiles and lazily loads them from its own Pages origin.
- Russian catalogue, character and relationship metadata: [Shikimori public API](https://shikimori.io/api/doc). Source attribution stays with the cached title profile; no Shikimori account token or paid API key is used.

- High-resolution catalogue banners: [AniList GraphQL Media](https://docs.anilist.co/reference/object/media), matched by MAL ID. Russian descriptions continue to come from Shikimori.
- Confirmed cross-media relationships: [Wikidata/Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API), linked through the title's Wikipedia page; Wikidata structured data is CC0. Images from Commons retain their source URLs; see each file page for its individual license.


AnimeGO provider/episode attributes were cross-checked against [AnimeParsers](https://github.com/YaNesyTortiK/AnimeParsers) at `cac4c83e03e43f2829506ef202a1279a4e0b78bf`, MIT (YaNesyTortiK). The adapter uses MediaVault’s source-only HTTP client; reference-package sessions and token collections are not imported. Player behavior was also reviewed against [the anime-dl-core author’s article](https://habr.com/ru/articles/1079156/). Existing `anime-dl-core` remains pinned to 0.5.1.

The eight-player integration fixtures in `tests/fixtures/players` are public saved
responses from `ialakey/anime-dl-core` commit
`f23b7c1b1403c7adc7eaa60ba6323a75e35c9771` (MIT, license above). They cover the
formats discussed in the article, including Kodik's decoded `ref`, CVH's MP4
keys, VK's `apiPrefetchCache`, Animedia's `data-vlnk`, and the retired
SovetRomantica format. Fixture success is separate from live network success.

- Playwright for Python 1.62.0 (Apache-2.0) and Chromium (BSD-style and third-party notices) run only on the server for public dynamic players; browser contexts contain no Google profile. Sources: https://github.com/microsoft/playwright-python and https://www.chromium.org/Home/chromium-security/ .

- Public trailer preparation: [yt-dlp](https://github.com/yt-dlp/yt-dlp), 2026.10.21, [Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE). Its optional default dependencies retain their respective licenses. Only catalogue-listed public trailers are accepted; no credentials, paywall or DRM bypass is configured. FFmpeg/ffprobe are provided by the server distribution under their packaged licenses.

Russian manga adapter behavior and current HTML selectors were cross-checked
against [Keiyoushi extensions-source](https://github.com/keiyoushi/extensions-source/tree/b2f43180511e576bb235800e8958531489d6692b)
(Apache-2.0), especially MangaPoisk, MangaHub, MangaBuff, MultiChan and GroupLe.
MediaVault uses its own Python implementation; it does not bundle Android clients,
authentication interceptors, site user hashes or challenge bypasses.
JSZip 3.10.1 is additionally bundled as a lazy module for the native CBZ reader
under its MIT option; the full license is included in the npm package.
Ratings retain platform attribution and source links: Shikimori, MyAnimeList/Jikan,
AniList and Kitsu; no paid credentials are used.

## Reader translation and music (5.4)

Tesseract (Apache-2.0), CTranslate2 (MIT), SentencePiece (Apache-2.0) and Pillow (HPND) power the optional local OCR/translation pipeline. The separately downloaded Argos English–Russian 1.9 model retains its upstream metadata and README with OPUS/dataset credits. See https://github.com/argosopentech/argos-translate and https://argos-net.com/v1/translate-en_ru-1_9.argosmodel . No code from the GPL manga-image-translator/mokuro projects or MPL Suwayomi-WebUI is copied.

AnimeThemes supplies song credits through its public API: https://animethemes.moe/ . Spotify/YouTube playback and playlist actions remain with their official services; no audio downloads or rights are granted by this application. Research, limits and setup: [docs/reader-music.md](docs/reader-music.md).

The short Dandadan excerpt in `translation-demo.html` is artwork by Yukinobu Tatsu, included to illustrate machine translation. The artwork is excluded from the application code license; its source is credited in the demonstration. The public demo contains only a cropped excerpt and precomputed real OCR/model output.

## Online playback and reader 5.5

- HLS.js 1.6.13, Apache-2.0: https://github.com/video-dev/hls.js . Loaded only for HLS MediaSource playback.
- MangaLib public field formats were reviewed against Keiyoushi LibGroup at f1edb0341163935686ba09a444eef092287779f3 (Apache-2.0). MediaVault implements its own key-free client and does not copy authentication or restriction bypasses.
- MangaDex free public API: https://api.mangadex.org/docs/ . Scanlation images retain their original owners' rights; API access does not grant redistribution rights.
- Opening/ending annotations: AniSkip https://api.aniskip.com/ . Music credits: AnimeThemes. Artist identities: MusicBrainz (core data CC0), with Russian Wikidata descriptions (CC0) and Wikipedia extracts (CC BY-SA, source links retained).
- YouTube music and trailers use the official IFrame Player API https://developers.google.com/youtube/iframe_api_reference . Videos remain visible and controlled by YouTube; MediaVault does not extract or download their audio.

- OpenCV 4.12.0 (opencv-python-headless 4.12.0.88), Apache-2.0: https://github.com/opencv/opencv . Used on CPU for connected speech interiors; no page images are sent to an external OCR service.

## Libre Manga Translator and video reconstruction 5.6

- Libre Manga Translator, mrdhnto, commit `39a95be1890e2ea3e227052976bbaf576a8eb7b3`, AGPL-3.0-or-later. The standalone adapted web engine and corresponding source are in [lmt/](lmt/), full license [lmt/upstream/LICENSE](lmt/upstream/LICENSE). Engine settings link to source/license. Native client communicates with it via MessageChannel. See [integration and modifications](docs/libre-manga-integration.md).
- ONNX Runtime Web 1.30.0 (MIT), https://github.com/microsoft/onnxruntime ; WebLLM 0.2.86 (Apache-2.0), https://github.com/mlc-ai/web-llm . Model weights retain upstream licenses; they are downloaded separately only after opt-in, not included in the Pages artifact.
- AMD FidelityFX FSR1 1.0.2, MIT, via agyild's mpv luma port. Full notice, original shader and source SHA256: [src/vendor/fsr1](src/vendor/fsr1/). WebGL2 binding and guarded flat-field RCAS preserve the original EASU/RCAS algorithms. Public notice is `FSR1-LICENSE.txt`. FSR is not a neural model.
- Lanczos3 is the classical windowed-sinc reconstruction kernel, implemented directly for WebGL; no third-party neural weights are involved. [Research, alternatives and device limits](docs/video-upscalers.md).

- Quality profile 5.6.1 adds PaddleOCR Korean PP-OCRv5 (Apache-2.0) via the monkt ONNX conversion pinned to `407d31ecdc555de8282c578889774861eea2667e`. The full-Hangul dictionary is bundled in `lmt/upstream/dicts/ppocrv5_korean_dict.txt`; ONNX model SHA256 is verified before use. OpenAI-compatible VLM/SoM requests use our AGPL adapter `lmt/vision.js`; no Gemini client or paid account is activated.

### Кириллические шрифты читалки

Comic Relief (Jeff Davis), Pangolin (Kevin Burke) и Neucha (Jovanny Lemonad) —
SIL Open Font License 1.1. Файлы WOFF2 поставляются с сайта MediaVault, без
запросов к Google Fonts. Лицензии, точные исходные URL/ревизия Google Fonts,
размеры и SHA-256 находятся в `reader-fonts/`. Сохранены Latin/Cyrillic и знаки
пунктуации; русские 66 букв, включая Ё/ё, проверены после конвертации.

Нативный ONNX-мост и перевод отдельных реплик перенесены для воспроизводимых
измерений из ветки `codex/manga-backend-processing`, commit `cc005d4537d040b8df38a63617af949529c447bf`.
Он не включает модели или токены и не меняет работающий importer.

## Локальные переводчики и дополнительные детекторы (26.10.2026)

- wllama 3.8.1 (MIT), https://github.com/ngxson/wllama; hash-wasm 4.12.0 (MIT), https://github.com/Daninet/hash-wasm. Реальный llama.cpp/WASM/WebGPU, без внешнего сервиса перевода.
- Tencent Hy-MT2 1.8B GGUF (Apache-2.0): закреплённые ревизия, размеры и SHA-256 в `src/hymt-models.js`.
- IndexTeam Index-Translate 2B GGUF (Apache-2.0), https://github.com/bilibili/Index-Translate; ревизия и SHA-256 в `src/index-models.js`. Официальный китайский prompt, greedy decoding; рекламные бенчмарки автора не считаются нашими результатами.
- leoxs22/manga-panel-detector-yolo26n, ревизия `40a2854663d537563cfb95c370288a84c6505b9a`, AGPL-3.0, Manga109-s attribution. ONNX-конверсия mednasserallah закреплена на `f6b7f3cb2bada1ec7d8b16501f9c984890811445`. Метаданные ONNX подтверждают AGPL-3.0, несмотря на Apache-метку конверсии. Классы: frame=0, text=1. Изображения Manga109-s не поставляются.
- Kellenok/PP-OCRv6_manga v0.2 (Apache-2.0), ревизия `62375557b5b0a4b2bc8e05484a97c7ea1df7229e`. Детектор DB и CTC recognizer поставляются отдельно; включён полный словарь (18 708 символов). Web postprocess использует прямоугольный DB unclip, не точный полигональный OpenCV unclip.
- mosesb/best-comic-panel-detection, `bbab11504194d0b341ac3f6099f3592aa0604ae3`, YOLOv12x, только панели. Карточка помечена Apache-2.0, архитектура/рантайм Ultralytics AGPL-3.0; сохраняем обе ссылки и применимые требования AGPL к нашему адаптеру. Веса не включены в Git/Pages.
- MAGI, Ragav Sachdeva / Andrew Zisserman, The Manga Whisperer, https://github.com/ragavsachdeva/magi, https://huggingface.co/ragavsachdeva/magi, `15ad498ad45093ad3b833d625728220c6309ad99`. В upstream не указан отдельный LICENSE; исходники/веса MAGI не перепубликуются в проекте. Наш самостоятельно реализованный detection-only адаптер использует проверенные safetensors и Transformers, не `trust_remote_code`. Модель скачивается оператором отдельно для сравнений. OCR/character clustering MAGI не объявляются реализованными.


### Пакетный VM JSON-путь (27 октября 2026)

- `src/manga-canvas.worker.js` импортирует Telea из Libre Manga Translator; новый изолированный Worker и `src/manga-typeset.js` распространяются под AGPL-3.0-or-later. Полный соответствующий исходник опубликован в этом репозитории; текст лицензии — `lmt/upstream/LICENSE`. Связь читалки с Worker — стандартные сообщения и ImageBitmap. Шрифты остаются под SIL OFL1.1.
- Google Gen AI Python SDK `google-genai==2.33.0`, Apache-2.0: https://github.com/googleapis/python-genai . API-ключ принадлежит владельцу проекта и не включается в исходники/Pages. Используются только бесплатные Gemma4; платные Gemini fallback по умолчанию отсутствуют.
- redis-py6.4.0 (MIT), https://github.com/redis/redis-py . Сервис использует отдельный официальный Redis7.4.6 image; лицензии Redis относятся к серверному контейнеру и поставляются upstream. Данные перевода шифруются до записи в Redis/SQLite.

### Moebius

Moebius (hustvl/Moebius, ECCV 2026) and the browser/ONNX port [simonw/moebius-web](https://github.com/simonw/moebius-web) use Apache-2.0. Adapted helpers in lmt/moebius retain attribution and the license. Source revision: 080be6e737ec976130e260d34707d7d9b7f63d5b. Model revision: 5bf1ef5d2861ec01a727183a3f95dc64f352120e. Weights are downloaded on demand and never committed. This is a separate neural model, not LaMa or MangaJaNai.

### Additional Cyrillic lettering

Ruslan Display, Marck Script, Press Start 2P and PT Serif are distributed under SIL OFL 1.1. Each bundled WOFF2 has its original license file. reader-fonts/manifest.json records immutable source URLs, SHA256 and verified Russian glyph coverage. Auto typography maps SFX, handwriting, system/game UI and narration to these fonts; earlier choices remain available.

The owner can explicitly select Gemini models. Gemini API billing and project quotas apply separately from a Google AI Pro subscription. No paid model is used as an invisible fallback from Gemma.

Moebius uses a separate `onnxruntime-web-moebius` package alias pinned to ONNX Runtime Web 1.27.0 (MIT), matching the upstream lockfile. Its WASM/MJS assets and license are bundled separately under `lmt/moebius-ort/`; detector and LaMa runtime versions are unchanged.

### MI-GAN and Russian hyphenation

- MI-GAN, Picsart AI Research / Andranik Sargsyan: https://github.com/Picsart-AI-Research/MI-GAN . Code and author-provided weights are MIT; both original notices are in `lmt/licenses/MI-GAN-*-MIT.txt`. The author-linked ONNX pipeline is pinned to `andraniksargsyan/migan` revision `406830d0fa60666da0071c342ad2fbc8f30c5c64`, `migan_pipeline_v2.onnx`, SHA-256 `6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b`. Weights are not redistributed in Git or Pages. The browser adapter performs actual ONNX inference with the official uint8 NCHW/inverted-mask contract.
- `hyphen` 1.14.1, Yevhen Tiurin, ISC: https://github.com/ytiurin/hyphen . Only the Russian pattern module is bundled for canvas line breaking. Original notice: `lmt/licenses/hyphen-ISC.txt`.
- The chapter pipeline, cleanup/renderer integration and worker changes remain published as corresponding integration source alongside the AGPL Libre Manga Translator attribution.
