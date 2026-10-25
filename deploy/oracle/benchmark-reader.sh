#!/usr/bin/env bash
# Isolated measurements on the existing VM. No production Compose/.env mounts.
set -euo pipefail
umask 027
revision="${1:?Pass a reviewed immutable Git SHA}"
stage="${2:-prepare}"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ "$stage" =~ ^(prepare|prepare-lmt|upscale|inventory)$ ]] || exit 2
root=/opt/mediavault-reader-bench
release="$root/$revision"
data="$root/data"
image="mediavault-reader-bench:${revision:0:12}"
mkdir -p "$root"
python3 - <<'PY'
import os,shutil
from pathlib import Path
m={x.split(':',1)[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if len(x.split())>=3 and x.split()[1].isdigit()}
if m['MemAvailable']<6*1024**3:raise SystemExit('Less than 6 GiB available RAM; benchmark postponed')
if shutil.disk_usage('/opt').free<8*1024**3:raise SystemExit('Less than 8 GiB free disk; benchmark postponed')
if os.getloadavg()[0]>1.5:raise SystemExit('VM is busy; benchmark postponed')
PY
if [[ "$stage" == prepare || "$stage" == prepare-lmt ]]; then
  mkdir -p "$release" "$data" "$data/tmp" "$data/benchmark"
  chown 1000:1000 "$data" "$data/tmp" "$data/benchmark"
  if [[ ! -d "$release/.git" ]]; then
    git init -q "$release"
    git -C "$release" remote add origin https://github.com/Onikri/MediaVault.git
  fi
  [[ "$(git -C "$release" remote get-url origin)" == https://github.com/Onikri/MediaVault.git ]] || exit 3
  git -C "$release" fetch --depth=1 origin "$revision" >"$root/git.log" 2>&1
  git -C "$release" checkout --detach FETCH_HEAD >>"$root/git.log" 2>&1
  [[ "$(git -C "$release" rev-parse HEAD)" == "$revision" ]] || exit 3
  if ! docker build -f "$release/server/Dockerfile" -t "$image" "$release" >"$root/build.log" 2>&1; then
    tail -70 "$root/build.log";exit 4
  fi
  if [[ "$stage" == prepare ]]; then docker run --rm --name mediavault-reader-model-prepare --cpus=1 --memory=3g --memory-swap=3g \
    --cap-drop=ALL --security-opt=no-new-privileges \
    -v "$data:/data" -e TMPDIR=/data/tmp "$image" \
    python scripts/install-mangajanai.py --directory /data/mangajanai >"$root/models.log" 2>&1 || { tail -30 "$root/models.log";exit 5; }; fi
  curl -fsSL https://raw.githubusercontent.com/mrdhnto/libre-manga-translator/39a95be1890e2ea3e227052976bbaf576a8eb7b3/docs/images/raw-sample.jpg -o "$data/benchmark/page.jpg"
  echo '56ed1dde6e8d880f1db136d1b2861262449b7311c5eefa9454c59613f347ea37  '"$data/benchmark/page.jpg" | sha256sum -c -
  chmod 644 "$data/benchmark/page.jpg"
  printf 'PREPARED image=%s revision=%s\n' "$image" "$revision"
elif [[ "$stage" == upscale ]]; then
  docker image inspect "$image" >/dev/null
  docker run --rm --name mediavault-reader-upscale-measure --cpus=2 --memory=4g --memory-swap=4g \
    --cap-drop=ALL --security-opt=no-new-privileges -v "$data:/data" \
    -e TMPDIR=/data/tmp -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 \
    "$image" python scripts/benchmark-reader.py --mode upscale --threads 2 --models /data/mangajanai \
    --data /data/benchmark --image /data/benchmark/page.jpg --runs 2 --tile 128 \
    --output /data/benchmark/upscale-a1.json >"$root/upscale.log" 2>&1 || { tail -30 "$root/upscale.log";exit 6; }
  cat "$data/benchmark/upscale-a1.json"
else
  df -h "$root"
  docker stats --no-stream --format '{{.Name}} CPU={{.CPUPerc}} RAM={{.MemUsage}}'
  for log in build models upscale; do
    [[ ! -f "$root/$log.log" ]] || { printf '\n%s\n' "$log";tail -4 "$root/$log.log"; }
  done
fi
