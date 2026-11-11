"""Admin-written source routing identity; no user proxy URLs or credentials."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def configuration():
    path = Path(os.getenv('DATA_DIR', '/data')) / 'manga-source-routes.json'
    try:
        if path.stat().st_size > 16384:
            return {}
        value = json.loads(path.read_text())
        if not re.fullmatch(r'[a-f0-9]{64}', value.get('revision', '')):
            return {}
        hosts = value.get('hosts')
        if not isinstance(hosts, list) or not 1 <= len(hosts) <= 128:
            return {}
        if any(not isinstance(h, str) or len(h) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', h) for h in hosts):
            return {}
        if value.get('httpProxy') != 'http://suwayomi-jp-router:8080':
            return {}
        return {'revision': value['revision'], 'hosts': hosts, 'httpProxy': value['httpProxy']}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def routed(url, config):
    try:
        host = urlsplit(url or '').hostname or ''
    except ValueError:
        return False
    return any(host == domain or host.endswith('.' + domain) for domain in config.get('hosts', []))
