"""Install official MangaJaNai releases into a private model directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / 'server' if (ROOT / 'server').is_dir() else ROOT) / 'mangajanai-models.json'


def install(archive, directory, *, download=None):
    import requests
    directory = Path(directory)
    cache = directory / '.archives'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / archive['name']
    def checksum(path):
        with path.open('rb') as file:
            return hashlib.file_digest(file, 'sha256').hexdigest()
    if not target.is_file() or target.stat().st_size != archive['bytes']:
        with tempfile.NamedTemporaryFile(dir=cache, suffix='.partial', delete=False) as file:
            temporary = Path(file.name)
            try:
                response = (download or requests.get)(archive['url'], stream=True, timeout=(15, 90))
                with response:
                    response.raise_for_status()
                    total = 0
                    for chunk in response.iter_content(1024 * 1024):
                        total += len(chunk)
                        if total > archive['bytes']:
                            raise ValueError('Official model archive exceeds recorded size')
                        file.write(chunk)
                file.close()
                if total != archive['bytes']:
                    raise ValueError('Incomplete official model archive')
                if archive.get('sha256') and checksum(temporary) != archive['sha256']:
                    raise ValueError('Official model archive checksum mismatch')
                os.replace(temporary, target)
            finally:
                file.close()
                temporary.unlink(missing_ok=True)
    digest = checksum(target)
    if archive.get('sha256') and digest != archive['sha256']:
        raise ValueError('Cached model archive checksum mismatch')
    output = directory / archive['name'].removesuffix('.zip')
    with tempfile.TemporaryDirectory(dir=directory, prefix='.install-') as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(target) as source:
            total = 0
            for info in source.infolist():
                path = PurePosixPath(info.filename.replace('\\', '/'))
                if path.is_absolute() or '..' in path.parts or ':' in info.filename:
                    raise ValueError('Invalid official model archive path')
                total += info.file_size
                if total > 2_500_000_000 or info.file_size > 700_000_000:
                    raise ValueError('Model extraction exceeds limit')
                # Never install executable Python/pickle helpers from an archive.
                if path.suffix.lower() not in {'.pth', '.onnx', '.safetensors', '.txt', '.md'}:
                    continue
                destination = staging.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as src, destination.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
        if not output.exists():
            staging.rename(output)
    receipt = {'archive': archive['name'], 'source': archive['url'], 'sha256': digest,
               'license': 'CC-BY-NC-4.0', 'release': archive['release']}
    (directory / (archive['name'] + '.json')).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / '.codex-local' / 'models' / 'mangajanai')
    parser.add_argument('--archive', action='append', help='Exact archive name from server/mangajanai-models.json')
    parser.add_argument('--all', action='store_true', help='Install all stable official releases')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    archives = json.loads(MANIFEST.read_text(encoding='utf-8'))['archives']
    if args.list:
        for item in archives:
            print(item['name'], item['bytes'], 'bytes')
        return
    selected = archives if args.all else [a for a in archives if a['name'] in (args.archive or ['MangaJaNai_V1_ModelsOnly.zip', 'IllustrationJaNai_V3denoise.zip'])]
    if args.archive and set(args.archive) - {a['name'] for a in archives}:
        parser.error('Unknown archive; use --list')
    for item in selected:
        print('Installing', item['name'], flush=True)
        print(json.dumps(install(item, args.directory)), flush=True)


if __name__ == '__main__':
    main()
