# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS lmt-build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY lmt ./lmt
COPY scripts/build-lmt.mjs ./scripts/build-lmt.mjs
COPY src/vendor/fsr1/LICENSE ./src/vendor/fsr1/LICENSE
RUN node scripts/build-lmt.mjs

FROM python:3.12-slim-bookworm
ENV CHROMIUM_PATH=/usr/bin/chromium PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates chromium tesseract-ocr tesseract-ocr-eng libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/requirements.txt server/requirements-service.txt server/requirements-manga.txt ./
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ] || [ "$(uname -m)" = "aarch64" ]; then \
      pip install --no-cache-dir torch==2.10.0 torchvision==0.25.0; \
    else pip install --no-cache-dir torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu; fi
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements-manga.txt; \
    else pip install --no-cache-dir -r requirements-manga.txt; fi
RUN useradd --uid 1000 --create-home vault && mkdir /data && chown vault:vault /data
COPY --chown=vault:vault --chmod=0644 server/*.py ./
COPY --chown=vault:vault server/mangajanai-models.json ./
COPY --chown=vault:vault --chmod=0644 scripts/benchmark-reader.py scripts/install-mangajanai.py ./scripts/
COPY --from=lmt-build --chown=vault:vault /build/dist/lmt /app/lmt
RUN chmod 0755 /app/scripts
ENV LMT_ASSETS_DIR=/app/lmt
USER vault
RUN python scripts/install-mangajanai.py --list >/dev/null && python scripts/benchmark-reader.py --mode inventory >/dev/null
EXPOSE 7860
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--no-access-log"]
