# Pause-frame depth and character recognition

The owner supplied `depthfx_studio.html` and a screen recording. MediaVault adapts
its smoothstep depth cutoff, Hermite S-curve, light-mask exponent 1.25, falloff .38,
and sinusoidal animation into an alpha-only WebGL overlay. It does not displace
UVs, move/duplicate the video, add a second video decoder, or reconstruct texture.
The 12-second cycle moves through relative depth; reduced-motion uses a static
cutoff and hidden tabs stop drawing. Selected characters lift the shadow over a
depth-connected surface, with a soft fill rather than a bright contour/halo.
Depth alone cannot guarantee semantic instance boundaries, especially where two
characters stand at the same distance. Selection is a depth-surface aid, not SAM.

## Actual model

- Depth Anything V2 **Small**, Apache-2.0 (large/base are not substituted).
- ONNX Community export, immutable revision `4472b7362082ad9968fee890ca0f1e5aca36b93d`.
- `onnx/model_quantized.onnx`, 27,258,801 bytes.
- SHA-256: `fcf51f1b230362b28690bb9d1809bf0431f29cad20534e3f589bd7285547f20d`.
- Official sources: https://github.com/DepthAnything/Depth-Anything-V2 and
  https://huggingface.co/onnx-community/depth-anything-v2-small .
- Actual ONNX Runtime WASM inference in an isolated worker; RGB/ImageNet planar
  input, maximum side 392, dimensions rounded to patch multiples of 14. This is
  relative near/far depth, not metric distance. No brightness/centre heuristic is
  presented as neural depth.

First use offers the 27 MB model download. Verified bytes go into the existing
user-selected model folder, or persistent browser Cache Storage when unavailable.
A changed/corrupt file is rejected. No weights or captured video frames enter Git.
Captured frames/depth/recognition results stay in bounded in-memory caches (4
frames); the worker is cancelled while busy on resume and released after 15 idle
seconds of playback. Turning the effect off preserves ordinary video playback.

## Characters

The official AnimeTrace API (https://www.animetrace.com/api-docs/) supplies bounded
normalized boxes and candidate names. Enabled/default model IDs come from its
model-list endpoint instead of a hardcoded model name. The default operation is
an explicit pause-frame button; optional automatic recognition is separately
controlled in player settings, debounced and limited to one request per 10 s.
Only a downscaled JPEG frame is sent, without cookies, Google tokens or source
URLs. Results are not treated as certain when multiple distinct names are offered,
even if the provider's `not_confident` flag is false. No confidence percentage or
unrecognized name is invented. Seeking, changing episodes and resuming invalidate
outstanding results. Public recognition is external and may be unavailable; depth
rendering and playback continue independently.

## Validation

Actual neural inference is separate from contract tests. Local Chromium/WASM ran
the checksummed 27 MB model against the owner's cropped reference frame at
392x224, producing all 256 normalized depth levels in ~0.8–1.1 s on this machine.
Raw output and the inference report remain in project-private test output. This
is not a phone/GPU speed claim. One real AnimeTrace request recognized Edward;
the armour character returned contradictory candidates and is marked unresolved.

Node tests cover preprocessing, the breathing cycle, letterbox coordinates,
depth connectivity and malformed/ambiguous provider answers. The browser contract
uses a fixture depth worker/API with real video decoding, WebGL and React at
390/1280 px, testing explicit download/recognition, cancellation and seek/resume.
Full-player visual previews use recorded real depth/API data, not fresh inference.
Depth inference does not use a paid API or require an Oracle model deployment.

## Russian names and ambiguous characters

Shikimori's Russian character names are joined to AniList native/Latin aliases
by normalized full names (AniList character IDs are not assumed to be MAL IDs).
Only Russian labels are displayed. On ambiguity or a missing Russian name,
bounded crops containing the detected face and surrounding body context are sent
in one request to `gemini-3.5-flash-lite`. The prompt labels each crop and target
face, includes the anime title/aliases, known season/episode, playback timecode,
AnimeTrace candidates and the Russian roster, and explicitly permits unresolved
answers. Unknown episode/season values are not invented. Gemini names are checked
for Cyrillic output; malformed or duplicate IDs cannot silently replace a label.

This reuses `/reader/google/generate`: personal translation mode supplies one
existing account-scoped key; VM mode leaves key selection to the existing server
pool. Shared per-key quota/cooldown leases still apply. No credential enters the
recognition API, public labels, logs or persistent frame caches. Resume/seek aborts
the verifier and stale replies are discarded. Missing keys/API failures preserve
playback and any catalogue-backed names, with an actionable status message.

One actual Gemini 3.5 Flash Lite call through the VM pool identified the ambiguous
armour crop from the supplied recording as `Альфонс Элрик` in 2.22 seconds (HTTP
200). The real native-alias lookup localized Edward as `Эдвард Элрик`. Browser
contract tests separately use fixture APIs to verify Russian rendering, crop
submission, the exact model/episode/timecode, and VM key isolation at 390/1280 px.
API implementation references: https://ai.google.dev/gemini-api/docs/image-understanding
and https://ai.google.dev/gemini-api/docs/structured-output .
