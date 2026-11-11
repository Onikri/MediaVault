FROM python:3.12-slim-bookworm
ARG GOST_VERSION=3.3.3
ARG GOST_SHA256=4c704c92df6eeea8a3b08d0de4fd3c44343095a20136b3b6cf334f98d2f174ab
RUN apt-get update && apt-get install -y --no-install-recommends openvpn curl ca-certificates iproute2 iptables \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 2 --max-time 120 \
      "https://github.com/go-gost/gost/releases/download/v${GOST_VERSION}/gost_${GOST_VERSION}_linux_arm64.tar.gz" -o /tmp/gost.tar.gz \
    && echo "${GOST_SHA256}  /tmp/gost.tar.gz" | sha256sum --check \
    && tar -xzf /tmp/gost.tar.gz -C /usr/local/bin gost && rm /tmp/gost.tar.gz
WORKDIR /app
COPY gateway.py /app/gateway.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/gateway.py"]
