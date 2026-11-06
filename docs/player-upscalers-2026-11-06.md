# Real-time anime upscalers for the browser player (research, 2026-11-06)

Goal: replace the weak options in the player's "Улучшение" menu (Lanczos3, FSR1, FSRCNN, the
mobile WebGL path) with filters that actually improve anime, keeping Anime4K and its presets.
Everything below must run per frame in the browser (WebGPU, WebGL fallback), not offline.

## What is worth adding

| Filter | What it is | Strength | Cost | Browser status |
|---|---|---|---|---|
| **ArtCNN C4F16 / C4F32** (+ DS, DN variants) | Small CNN luma doubler for anime, single long skip connection. "C" models are meant for real-time playback; "R" models are offline. | Most favoured newer option for HD/WEB anime; better chroma handling in Artoriuz's metric tests. DS = denoise+sharpen, DN = denoise+soften. | C4F16 is light, C4F32 needs a modern GPU | GLSL for mpv upstream; already ported to WebGPU in NijiLucid |
| **CuNNy** (several sizes) | Small fast CNN 2× upscaler trained on visual novels and anime CG | Good quality per millisecond, many speed tiers, a natural replacement for the "mobile GPU" path | Lightest tiers run on integrated GPUs | GLSL upstream; ported to WebGPU in NijiLucid |
| **Ani4K v2 ArtCNN** (Sirosky) | ~47K-parameter ArtCNN trained for modern anime, Blu-ray/WEB to 2K/4K | Built exactly for our main source type (WEB releases) | Light | GLSL shader release |
| **AniSD ArtCNN** (Sirosky) | ArtCNN trained for SD and old anime | Removes compression artefacts on 480p/576p sources | Light | GLSL shader |
| **ACNet** (Anime4KCPP) | CNN from the Anime4KCPP project | Middle ground between Anime4K and ArtCNN | Medium | Ported in NijiLucid |
| **AMD CAS** (post pass) | Contrast-adaptive sharpening | Cheap final crispness after any upscaler; better than a plain sharpen | Very light | Simple fragment shader |
| **Deband** (post pass) | Removes banding in gradients | Streaming sources band a lot in skies and dark scenes | Light | Simple fragment shader |

## Keep

* **Anime4K** and its official mode chains (A, B, C and the A+A / B+B combos). Strongest at
  restoring SD and badly encoded sources. Several guides warn that on clean HD it can wipe
  fine detail, so it should not be the only choice.

## Remove or demote

* Lanczos3, FSR1 (EASU/RCAS and soft) and FSRCNN: not anime-specific, little visible gain.
  CAS covers the "a bit sharper" use case at lower cost.
* The current "mobile GPU" WebGL path, replaced by the lightest CuNNy tier.

## Not real time in a browser

* **Real-ESRGAN AnimeVideo-v3 / Compact** via onnxruntime-web (WebGPU). Upstream reports about
  22 fps at 720p on a V100 in PyTorch. A browser extension running it caps itself around 15 fps
  and halves the inference resolution on weaker GPUs. It suits a paused frame or a screenshot,
  not playback.
* AnimeJaNai, Real-CUGAN, ESRGAN: TensorRT/desktop territory.

## Suggested menu after the change

* **Автоматически**: picks by GPU tier and source height.
* **Чёткость HD**: ArtCNN C4F16 (C4F32 on strong GPUs), for 1080p WEB/Blu-ray.
* **Современное аниме в 4K**: Ani4K v2 ArtCNN.
* **Старое и SD**: AniSD, or Anime4K Mode A.
* **Быстро**: CuNNy, light tier.
* **Anime4K**: modes A, B, C and combos, as today.
* Post filters as switches: **резкость (CAS)** and **убрать полосы (deband)**.

## Integration notes

* The mpv `//!HOOK` GLSL shaders need translating into our WebGPU/WebGL pipeline (one render
  pass per `//!DESC` block, with textures for the intermediate `//!SAVE` targets). NijiLucid has
  done this for ArtCNN, CuNNy and ACNet. Reusing its code depends on its licence, which has to be
  checked first, along with the upstream licences of ArtCNN, CuNNy and Sirosky's models. Any
  model weights or shaders we ship must be listed in THIRD_PARTY.md.
* All of these are 2× doublers. Non-2× targets (720p on a 1080p screen) need a good downscaler
  after the pass, otherwise the result loses sharpness.
* Do not stack two luma upscalers. Post passes (CAS, deband) and the colour LUT pass chain fine.
* Measure on real GPUs before shipping: frame time at 720p and 1080p input on an integrated
  GPU, a mid-range discrete GPU and a phone.

## Sources

* CuNNy: https://github.com/funnyplanter/CuNNy
* ArtCNN: https://github.com/Artoriuz/ArtCNN
* Artoriuz, mpv resampler evaluation: https://artoriuz.github.io/blog/mpv_upscaling.html
* Ani4K v2 ArtCNN release: https://github.com/Sirosky/Upscale-Hub/releases/tag/Ani4k-v2-ArtCNN
* MPV Anime Build (Ani4Kv2, AniSD): https://chinna95p.github.io/mpv-anime-build/
* ArtCNN vs FSRCNNX vs Ani4K discussion: https://github.com/dyphire/mpv-config/discussions/78
* Shader guides: https://mpvconfig.github.io/docs/shaders.html, https://deepwiki.com/stax76/awesome-mpv/5-shaders-and-video-processing
* NijiLucid (WebGPU ports of ArtCNN, CuNNy, ACNet): https://github.com/chenmozhijin/Anime4K-WebExtension
* Anime4K-WebGPU: https://github.com/Anime4KWebBoost/Anime4K-WebGPU
* WebSR: https://github.com/sb2702/websr
* realesr-animevideov3 ONNX for onnxruntime-web: https://huggingface.co/skillsafe-ai/realesr-animevideov3
* AniWebScale (browser fps limits): https://github.com/Daniel-Nikoulchine/AniWebScale
* Real-ESRGAN AnimeVideo-v3 timings: https://github.com/xororz/Real-ESRGAN/blob/master/docs/anime_comparisons.md
* Anime4K: https://github.com/bloc97/anime4k
