#!/usr/bin/env bash
# Install only onto an EXISTING VM. Does not create/resize cloud resources or enable billing.
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
  echo 'Run with sudo on the selected VM.' >&2
  exit 1
fi
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$source_dir" == /opt/mediavault ]]; then
  echo 'Run from a separate checkout, not /opt/mediavault.' >&2
  exit 1
fi
apt-get update
apt-get install -y python3-venv ffmpeg nginx certbot python3-certbot-nginx rsync
id mediavault >/dev/null 2>&1 || useradd --system --home /var/lib/mediavault --shell /usr/sbin/nologin mediavault
install -d -m 700 -o mediavault -g mediavault /var/lib/mediavault
install -d -m 755 /opt/mediavault
rsync -a --exclude=.git --exclude=.venv --exclude=node_modules --exclude=runtime-data --exclude=.env --exclude=oauth-client.json --exclude=test-output "$source_dir/" /opt/mediavault/
python3 -m venv /opt/mediavault/.venv
/opt/mediavault/.venv/bin/pip install -r /opt/mediavault/server/requirements-runtime.txt
if [[ ! -f /etc/mediavault.env ]]; then
  install -m 600 /opt/mediavault/deploy/mediavault.env.example /etc/mediavault.env
fi
install -m 644 /opt/mediavault/deploy/mediavault-api.service /etc/systemd/system/
install -m 644 /opt/mediavault/deploy/mediavault-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mediavault-api mediavault-worker
printf '%s\n' 'Installed. Complete HTTPS and one-time Google authorization in docs/automatic-import.md.'
