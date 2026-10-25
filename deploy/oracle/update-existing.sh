#!/usr/bin/env bash
# Run on the existing VM as its administrator. No provisioning or billing operations.
set -euo pipefail
commit="${1:?Pass the reviewed 40-character Git commit}"
[[ "$commit" =~ ^[a-f0-9]{40}$ ]] || { echo 'Expected an immutable commit SHA.' >&2; exit 2; }
project=/opt/mediavault
[[ -d "$project/.git" && -f "$project/deploy/oracle/.env" ]] || { echo 'Existing installation not found.' >&2; exit 2; }
[[ "$(git -C "$project" remote get-url origin)" == https://github.com/Onikri/MediaVault.git ]] || { echo 'Unexpected repository origin.' >&2; exit 2; }
[[ -z "$(git -C "$project" status --porcelain --untracked-files=no)" ]] || { echo 'Tracked local edits exist; preserve them before updating.' >&2; exit 2; }
cd "$project/deploy/oracle"
active="$(docker compose exec -T importer python -c 'import sqlite3; db=sqlite3.connect("file:/data/tasks.sqlite?mode=ro",uri=True); print(db.execute("SELECT count(*) FROM tasks WHERE status IN (\"queued\",\"running\",\"cancelling\")").fetchone()[0])')"
[[ "$active" == 0 ]] || { echo 'Wait for current imports to finish before updating.' >&2; exit 3; }
previous="$(git -C "$project" rev-parse HEAD)"
container="$(docker compose ps -q importer)"
image="$(docker inspect --format '{{.Image}}' "$container")"
image_tag="$(docker inspect --format '{{.Config.Image}}' "$container")"
git -C "$project" fetch origin "$commit"
git -C "$project" switch --detach "$commit"
if ! docker compose build importer; then
  git -C "$project" switch --detach "$previous"
  echo 'Build failed; the running container was not replaced.' >&2
  exit 1
fi
rollback(){
  docker tag "$image" "$image_tag"
  git -C "$project" switch --detach "$previous"
  docker compose up -d --no-deps --force-recreate importer
  echo 'Previous importer image restored. Data and OAuth configuration were preserved.' >&2
}
if ! docker compose up -d --no-deps importer; then rollback; exit 1; fi
for attempt in $(seq 1 30); do
  if docker compose exec -T importer python -c 'import json,urllib.request; result=json.load(urllib.request.urlopen("http://127.0.0.1:7860/health",timeout=3)); assert result["version"]>=6 and result["voiceDiscovery"]' >/dev/null 2>&1; then
    echo "MediaVault importer updated to $commit; health version 6 confirmed."
    exit 0
  fi
  sleep 2
done
rollback
exit 1
