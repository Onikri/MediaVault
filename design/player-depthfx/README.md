# Pause-frame depth and character recognition

The owner supplied `depthfx_studio.html` and a screen recording. MediaVault adapts
its smoothstep depth cutoff, Hermite S-curve, light-mask exponent 1.25, falloff .38,
and sinusoidal animation into an alpha-only WebGL overlay. It does not displace
UVs, move/duplicate the video, add a second video decoder, or reconstruct texture.
The first pass starts fully transparent behind the scene and advances for six
seconds to cutoff .62. Subsequent ten-second breaths stay in the smaller .44–.62
range, keeping the far background shaded. Reduced-motion uses a static cutoff
and hidden tabs stop drawing. Selected characters lift the shadow over a
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
normalized face boxes and candidate names. Enabled/default model IDs come from
its model-list endpoint. A separate Gemini full-frame pass can find profiles,
armour, occluded faces and people missed by that face detector. The pause button
starts the face request in parallel, allows at most 350 ms for preliminary hints,
then sends one Google request for the whole downscaled frame and any available
ambiguous crops. Later face results can still provide names while Google works.
The Russian roster and face model list warm on pause using metadata only; image
upload still requires the button or separately enabled automatic recognition.
Manual calls have a two-second click guard plus the shared Google quota limiter;
automatic calls retain a ten-second guard. Complete frame results use the bounded
memory cache. Unavailable Google service preserves available face results without
caching that incomplete fallback as a final answer. A face API failure/empty
answer cannot prevent Gemini from searching the frame. One face request is bounded
to five seconds, Google to twelve; these are failure deadlines, not promised speed.
Google's normalized `[ymin,xmin,ymax,xmax]` body/face boxes are validated and
converted to the player's normalized coordinates. Invalid boxes and duplicates
are rejected. Ambiguity remains explicit; no confidence percentage is invented.
Resume, seek and episode changes cancel and invalidate outstanding work. Only the
JPEG and bounded anime context are sent, without Google OAuth tokens/source URLs
in the provider payload. Playback and depth rendering remain independent.

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
Only Russian labels are displayed. `gemini-3.5-flash-lite` receives the complete
frame plus up to three available ambiguous crops. The prompt includes anime
title/aliases, known season/episode, playback timecode, preliminary AnimeTrace
candidates and the Russian roster, and explicitly permits unresolved answers.
Unknown episode/season values are not invented. Gemini names are checked for
Cyrillic output and boxes remain tied to visible figures, not every character in
the roster. The whole-frame search runs even without detected faces.

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

## Hover refinement and current measurements

Each coarse body box limits a depth-connected flood from a robust face/upper-body
seed. A 3x3 median handles single-pixel depth noise. Masks are built once per depth
map/recognition result, not on pointer moves. Body hover tests these masks and
resolves overlapping coarse boxes by surface interior; labels support hover,
keyboard focus and click-to-pin. The GPU fades the selected mask in/out over about
160 ms without changing the breathing phase or running another model. This is
still relative-depth selection, not guaranteed semantic segmentation: adjacent
figures at equal depth can share parts of the surface.

Two real full-frame requests with **no face hints** recognized Edward and Alphonse
on the supplied recording frames (including armour with no visible face). VM
gateway round trips were 1.84 and 1.90 s, separate slots, 2,487/2,535 total tokens.
The client allows 350 ms for hints and adds image encoding/network time; quota,
congestion and provider latency can exceed a 3–4 s target. This small sample is not
a general recognition benchmark. Visual QA uses recorded real depth and Gemini
answers; browser contract tests use fixtures and real WebGL readback to verify
zero alpha on the very first pass, later darkening, mask lifting, body hover,
fallbacks, key isolation, caching and cancellation at 390/1280 px.
