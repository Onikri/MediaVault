#!/usr/bin/env bash
# Isolated A1 benchmark. Official pinned llama.cpp + Qwen; no public ports.
set -euo pipefail
umask 027
revision="${1:?Pass the SHA of an already prepared reader image}"
stage="${2:-prepare}"
variant="${3:-4b}"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ "$stage" =~ ^(prepare|lmt)$ ]] || exit 2
[[ "$variant" =~ ^(4b|baseline)$ ]] || exit 2
root=/opt/mediavault-reader-bench
data="$root/data"
reader="mediavault-reader-bench:${revision:0:12}"
llm=mediavault-reader-llm:b11887
network=mediavault-reader-bench
if [[ "$variant" == 4b ]]; then
  model=Qwen3-4B-Q4_K_M.gguf
  modelrepo=Qwen/Qwen3-4B-GGUF
  modelrev=bc640142c66e1fdd12af0bd68f40445458f3869b
  modelhash=7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5
else
  model=Qwen3-0.6B-Q8_0.gguf
  modelrepo=Qwen/Qwen3-0.6B-GGUF
  modelrev=23749fefcc72300e3a2ad315e1317431b06b590a
  modelhash=9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031
fi
[[ "$(uname -m)" == aarch64 ]] || { echo 'This benchmark requires ARM64'; exit 2; }
docker image inspect "$reader" >/dev/null
python3 - <<'PY'
import os,shutil,time
from pathlib import Path
if shutil.disk_usage('/opt').free<4*1024**3:raise SystemExit('Less than 4 GiB free disk')
deadline=time.monotonic()+180
while True:
 m={x.split(':',1)[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if len(x.split())>=3 and x.split()[1].isdigit()}
 if m['MemAvailable']>=10*1024**3 and os.getloadavg()[0]<=1.5:break
 if time.monotonic()>=deadline:raise SystemExit('VM remained busy or had less than 10 GiB available RAM; benchmark postponed')
 time.sleep(5)
print('VM ready: load1=%.2f availableGiB=%.2f'%(os.getloadavg()[0],m['MemAvailable']/1024**3),flush=True)
PY
if [[ "$stage" == prepare ]]; then
  mkdir -p "$root/llama-image" "$data/llm"
  chown 1000:1000 "$data/llm"
  chmod 0750 "$data/llm"
  curl -fL --retry 2 https://github.com/ggml-org/llama.cpp/releases/download/b11887/llama-b11887-bin-ubuntu-arm64.tar.gz -o "$root/llama-image/llama.tar.gz"
  echo '469436cab640d9edf74a447cb180902b996f7c448f9b0a1eb94663f71aba74a3  '"$root/llama-image/llama.tar.gz" | sha256sum -c -
  # The official ARM binary requires GLIBC_2.38; Debian bookworm is too old.
  cat >"$root/llama-image/Dockerfile" <<'DOCKER'
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libstdc++6 libgomp1 libcurl4t64 && rm -rf /var/lib/apt/lists/*
ADD llama.tar.gz /opt/
ENV LD_LIBRARY_PATH=/opt/llama-b11887
USER 1000:1000
ENTRYPOINT ["/opt/llama-b11887/llama-server"]
DOCKER
  docker build -t "$llm" "$root/llama-image" >"$root/llama-build.log" 2>&1 || { tail -30 "$root/llama-build.log";exit 3; }
  if [[ ! -f "$data/llm/$model" ]]; then
    curl -fL --retry 2 "https://huggingface.co/$modelrepo/resolve/$modelrev/$model" -o "$data/llm/$model.part"
    echo "$modelhash  $data/llm/$model.part" | sha256sum -c -
    mv "$data/llm/$model.part" "$data/llm/$model"
  fi
  echo "$modelhash  $data/llm/$model" | sha256sum -c -
  chmod 644 "$data/llm/$model"
  docker run --rm --network none --cpus=.25 --memory=128m --cap-drop=ALL --security-opt=no-new-privileges \
    -v "$data/llm:/models:ro" "$reader" python -c \
    'from pathlib import Path;import sys;p=Path(sys.argv[1]);assert p.open("rb").read(4)==b"GGUF";print("LLM weights readable by container uid=1000")' "/models/$model"
  docker run --rm --network none --cpus=1 --memory=1g --cap-drop=ALL --security-opt=no-new-privileges "$llm" --version
  echo LLM_PREPARED
  exit
fi
docker network inspect "$network" >/dev/null 2>&1 || docker network create "$network" >/dev/null
docker inspect mediavault-reader-llm >/dev/null 2>&1 && { echo 'An existing measurement is using the LLM container';exit 4; }
docker inspect mediavault-reader-lmt-measure >/dev/null 2>&1 && { echo 'An existing backend measurement container exists';exit 4; }
llm_id=''
backend_id=''
cleanup(){
  for id in "$backend_id" "$llm_id"; do
    [[ -n "$id" ]] || continue
    docker inspect --format '{{json .State}}' "$id" >>"$root/lmt-$variant-container-states.jsonl" 2>/dev/null || true
  done
  if [[ -n "$llm_id" ]]; then docker logs "$llm_id" >"$root/llm-$variant.log" 2>&1 || true;fi
  for id in "$backend_id" "$llm_id"; do
    [[ -n "$id" ]] || continue
    docker stop -t 15 "$id" >/dev/null 2>&1 || true
    docker rm "$id" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT
trap 'exit 143' TERM INT
llm_id=$(docker create --name mediavault-reader-llm --network "$network" \
  --cpus=2 --memory=4g --memory-swap=4g --cap-drop=ALL --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=64m -v "$data/llm:/models:ro" \
  "$llm" -m "/models/$model" --alias "${model%.gguf}" -c 4096 -t 2 --parallel 1 --host 0.0.0.0 --port 8081 --reasoning off --no-webui)
docker start "$llm_id" >/dev/null
# Poll from a temporary container on the private network; no host listener.
docker run --rm --network "$network" --cpus=.25 --memory=128m --cap-drop=ALL --security-opt=no-new-privileges "$reader" python -c '
import time,urllib.request
for i in range(120):
 try:
  urllib.request.urlopen("http://mediavault-reader-llm:8081/health",timeout=2);break
 except Exception:time.sleep(1)
else:raise SystemExit("LLM failed to start")
'
docker stats --no-stream --format '{{.Name}} CPU={{.CPUPerc}} RAM={{.MemUsage}}'
backend_id=$(docker create --name mediavault-reader-lmt-measure --network "$network" \
  --cpus=2 --memory=6g --memory-swap=6g --cap-drop=ALL --security-opt=no-new-privileges \
  -v "$data:/data" -e TMPDIR=/data/tmp -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 \
  -e LMT_LLM_URL=http://mediavault-reader-llm:8081/v1 -e "LMT_LLM_MODEL=${model%.gguf}" \
  "$reader" python scripts/benchmark-reader.py --mode "$stage" --threads 2 \
  --models /data/mangajanai --data /data/benchmark --image /data/benchmark/page.jpg \
  --language Japanese --ocr manga-ocr --detector comic-text-detector --inpaint quality --runs 2 \
  --save-result "/data/benchmark/lmt-$variant-result.webp" --save-transcript "/data/benchmark/lmt-$variant-transcript.json" \
  --output "/data/benchmark/lmt-$variant-a1.json")
backend_start_status=0
docker start -a "$backend_id" >"$root/lmt-$variant.log" 2>&1 || backend_start_status=$?
backend_exit=$(docker inspect --format '{{.State.ExitCode}}' "$backend_id")
if [[ "$backend_start_status" -ne 0 || "$backend_exit" -ne 0 ]]; then
  tail -40 "$root/lmt-$variant.log";docker logs --tail 15 mediavault-reader-llm;exit 5
fi
cat "$data/benchmark/lmt-$variant-a1.json"
printf '\nLLM separate-container cgroup memory peak (includes file cache, not part of Python RSS):\n'
if docker exec mediavault-reader-llm cat /sys/fs/cgroup/memory.peak >"$data/benchmark/llm-$variant-memory-peak.txt"; then
  cat "$data/benchmark/llm-$variant-memory-peak.txt"
else echo 'cgroup memory peak unavailable';fi
docker stats --no-stream --format '{{.Name}} CPU={{.CPUPerc}} RAM={{.MemUsage}}'
docker logs --tail 10 mediavault-reader-llm
