# Developer-only extension of the EXISTING tested Oracle benchmark image.
FROM node:22-bookworm-slim AS browser-build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY lmt ./lmt
COPY reader-fonts ./reader-fonts
COPY scripts/benchmarks ./scripts/benchmarks
RUN node scripts/benchmarks/build-browser.mjs /browser
FROM mediavault-reader-bench:cc005d4537d0
USER root
RUN pip install --no-cache-dir sacrebleu==2.6.0
COPY --chown=1000:1000 scripts/benchmarks /quality/scripts/benchmarks
COPY --chown=1000:1000 server/lmt_onnx.py /quality/server/lmt_onnx.py
COPY --from=browser-build --chown=1000:1000 /browser /quality/browser
RUN chmod -R a+rX /quality
USER 1000:1000
WORKDIR /quality
