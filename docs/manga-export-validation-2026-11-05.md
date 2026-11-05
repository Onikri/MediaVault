# Device export validation · 2026-11-05

- Production build: main React application, dedicated VM renderer entry and
  attributed LMT build completed successfully.
- 37 relevant Node tests passed, including chapter/volume ranges, direct Google
  pipeline, translation settings and partial Drive upload without vault keys.
- 17 Python tests passed: owner isolation, verified binary staging, incomplete
  chapter rejection, real CBZ/ZIP/PDF creation, cleanup and encrypted cache reuse.
  Translation in these archive/queue tests is a fixture, not ML inference.
- Browser contract passed at 360 and 1280 px: real React controls, encrypted
  IndexedDB, complete cached chapter detection, binary page upload and download.
  API responses in this test are fixtures.
- Actual Oracle execution used **Gemini 3.5 Flash Lite** with two generated English
  speech-bubble pages. Google vision/translation and the reader's real Cyrillic
  renderer produced two Russian page images in **29.64 seconds**, including a
  transient provider failure and retry. Cleanup was the **algorithmic fast**
  mode; this check does not claim local neural inpainting inference or comprehensive
  image-quality validation.
- Actual external HTTPS test staged a **923404-byte PNG**, built a plaintext CBZ,
  downloaded and reopened it, verified exact image bytes and confirmed temporary
  export cleanup after download. The upload routing was adjusted according to
  [Caddy's path matcher rules](https://caddyserver.com/docs/caddyfile/matchers#path);
  the API independently retains its stricter per-endpoint body limits.
- Oracle update verified preservation of service encryption key, stored settings
  and all 78 existing import tasks. No Drive files were decrypted or rewritten by
  deployment.
