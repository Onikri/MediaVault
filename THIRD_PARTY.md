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
