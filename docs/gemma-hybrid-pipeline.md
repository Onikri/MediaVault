# Gemma: device → own VM → Google → device

This opt-in reader mode translates English, Japanese and Korean pages into Russian
without a separate OCR model. It does send the page preview to Google. The Google
key belongs to the server operator and is never included in the frontend bundle,
browser requests, translation cache or repository.

## Processing

1. The device runs the upstream RT-DETR Comic v4 INT8 detector at confidence 0.15.
   Stable region IDs contain the page index and source hash. Original pixel
   coordinates are retained. A WebP preview (quality 0.8, longest side 1280) carries
   red rectangles and numbered B labels. Detection can still miss text; a complete
   API answer is not a measurement of detector recall.
2. The existing authenticated backend receives up to four prepared pages. Its
   private LMT sidecar calls `gemma-4-31b-it` or `gemma-4-26b-a4b-it`. No browser API
   key, caller-selected upstream URL, local translator or OCR transcript is used.
3. The model reads the page and returns translation, speaker gender, speech
   register, font category, fill/outline, weight, italic, alignment and rotation
   for every supplied ID. The system instruction is published in
   [server/gemma-system.md](../server/gemma-system.md). Linked bubbles keep separate
   placements while sharing grammatical context. Unknown gender remains unknown.
4. The backend verifies the complete ID set, duplicate/missing rows, nonempty
   translations, statuses and bounded appearance values. Failed/incomplete answers
   use the other model; originals remain available on failure. The API transport
   uses a `{"regions":[...]}` envelope because dense top-level array schemas failed
   against the live Gemma endpoint. The normalized application result remains a
   per-page region array.
5. On the device, upstream LaMa removes only regions with valid translations.
   Unreadable/non-text regions are preserved. Cyrillic fonts are chosen by visual
   category (Comic Relief, Pangolin, Neucha, serif or monospace), then fitted to the
   original boxes. This approximates the original style; it does not identify or
   reproduce an arbitrary proprietary typeface. Layout failure does not replace
   the original with a partially blank page.

The reader batches pages that are already queued, prioritizes the current page,
and does not wait for four pages before starting. Cancel/close aborts outstanding
work. Chapter context contains recent Russian translations, is bounded in memory,
and is cleared when the vault locks. Rendered pages use the existing encrypted
device cache. Backend results use an owner-scoped AES-GCM cache; pending preview
images are removed from job memory after completion/cancellation.

## Limits and deployment

Each Google request has at most 4 images, 65 regions and 16,384 output tokens.
Dense pages and truncated outputs split into smaller calls without changing IDs.
Before generation, `countTokens` counts the request plus a conservative schema
allowance. SQLite reservations enforce at most 14,500 input tokens per rolling
minute, 15 generation requests/minute, a 12-second per-model gap and a configurable
rolling daily cap (`GEMMA_RPD`, default 1500/model). These are application ceilings,
not a promise of Google account entitlement. Provider 429/500/503 responses cool
down the affected model. Two backend workers share the model locks and ledger.

The key is read from `GEMMA_API_KEY_FILE`, default `/run/secrets/gemma-api-key`.
For the existing Oracle install it is `/data/secrets/gemma-api-key`, readable only
by the worker UID 1000. The existing authenticated `/reader/lmt/*` proxy covers the
new jobs; there is no new public port or authentication bypass.

[deploy/oracle/install-gemma.py](../deploy/oracle/install-gemma.py) builds an immutable
Git SHA, checks a candidate worker, retains the old worker for rollback and leaves
the importer, Caddy and other model sidecars intact. Keep all credentials, model
weights, test pages and local reports outside Git in `.codex-local/` on drive D.

## Verification boundaries

`npm test`, `npm run test:gemma` and `tests/test_gemma_gateway.py` check queue,
geometry, validation, quota persistence, cancellation/fallback contracts and UI.
Browser API responses and detector/render callbacks in the contract test are
mocked. Its Cyrillic Canvas font fitting is real; it is not an ML quality test.

Separate real inference smoke tests used RT-DETR, Google Gemma and LaMa on complex
EN/JA/KO pages. Private before/cleaned/after images and usage records stay in
`.codex-local/real-pipeline/`. The device smoke used native ONNX CPU on the Windows
test computer; its timings do not represent a phone GPU or Oracle ARM. Oracle and
live-site measurements must be recorded separately. AGPL upstream attribution and
corresponding integration source remain published with this repository.
