"""Reconcile the Suwayomi snapshot and Keiyoushi source tree without extracting APKs."""

import argparse
import csv
import json
import re
import tarfile
from collections import Counter
from pathlib import Path


PREFIX = 'eu.kanade.tachiyomi.extension.'
OPERATIONS = ('search', 'catalogue', 'metadata', 'chapters', 'pages', 'cbz', 'saved_links')
STATES = {'pending', 'implemented', 'verified', 'blocked', 'not_applicable'}
FIELDS = (
    'source_id', 'package', 'version', 'source', 'language', 'latest', 'configurable',
    'japan_route', 'upstream_revision', 'upstream_path', 'upstream_version', 'theme',
    'overrides', 'adapter',
    *OPERATIONS, 'evidence',
)


def upstream_packages(archive):
    packages, themes = {}, {}
    overrides = {}
    revision = None
    with tarfile.open(archive, 'r:gz') as source:
        for entry in source:
            if not entry.isfile():
                continue
            root, path = entry.name.split('/', 1)
            kotlin = re.fullmatch(r'(src/[^/]+/[^/]+)/src/.+\.kt', path)
            if kotlin:
                content = source.extractfile(entry).read().decode()
                declarations = re.findall(
                    r'(?m)^\s*(?:(?:open|final|protected|public)\s+)*override\s+'
                    r'(?:(?:suspend|inline|operator)\s+)*(?:val|var|fun)\s+'
                    r'((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*)', content,
                )
                overrides.setdefault(kotlin[1], set()).update(name.rsplit('.', 1)[-1] for name in declarations)
                continue
            if not path.endswith('/build.gradle.kts'):
                continue
            match = re.fullmatch(r'src/([^/]+)/([^/]+)/build\.gradle\.kts', path)
            theme_match = re.fullmatch(r'lib-multisrc/([^/]+)/build\.gradle\.kts', path)
            if not match and not theme_match:
                continue
            if not re.fullmatch(r'extensions-source-[a-f0-9]{40}', root):
                raise ValueError('Keiyoushi archive must be pinned to a 40-character revision')
            revision = root.removeprefix('extensions-source-')
            text = source.extractfile(entry).read().decode()
            library = re.search(r'(?m)^\s*libVersion\s*=\s*"([\d.]+)"', text)
            if theme_match:
                base = re.search(r'(?m)^\s*baseVersionCode\s*=\s*(\d+)\s*$', text)
                themes[theme_match[1]] = (library.group(1) if library else '', int(base[1]) if base else None)
                continue
            language, module = match.groups()
            theme = re.search(r'(?m)^\s*theme\s*=\s*"([^"]+)"', text)
            version = re.search(r'(?m)^\s*versionCode\s*=\s*(\d+)\s*$', text)
            package_name = re.search(r'(?m)^\s*pkgName\s*=\s*"([a-zA-Z0-9_.]+)"', text)
            key = package_name[1] if package_name else language + '.' + module
            packages[key if key.startswith(PREFIX) else PREFIX + key] = (
                f'src/{language}/{module}', theme.group(1) if theme else '',
                library.group(1) if library else '', int(version[1]) if version else None,
            )
    if not revision or not packages:
        raise ValueError('No revision-pinned Keiyoushi packages found')
    result = {}
    for package, (path, theme, library, version) in packages.items():
        base_lib, base_code = themes.get(theme, ('', 0 if not theme else None))
        library = library or base_lib
        upstream_version = f'{library}.{version + base_code}' if library and version is not None and base_code is not None else ''
        result[package] = (path, theme or 'standalone', upstream_version,
                           ' '.join(sorted(overrides.get(path, ()))))
    return revision, result


def make_rows(inventory, archive, previous, history):
    revision, upstream = upstream_packages(archive)
    installed = {row['pkgName']: row for row in inventory['extensions'] if row['installed']}
    if not installed:
        raise ValueError('Empty installed package list')
    sources = {}
    for source in inventory['sources']:
        sid = str(source['id'])
        if sid == '0':
            continue
        package = source['package']
        if sid in sources or not re.fullmatch(r'[1-9][0-9]{0,18}', sid) or package not in installed:
            raise ValueError(f'Invalid, duplicate or uninstalled source {sid} ({package})')
        extension = installed[package]
        identity = (package, extension['versionName'], source['lang'])
        prior = previous.get(sid, {})
        if prior and prior['package'] != package:
            raise ValueError(f'Source ID {sid} changed packages')
        if identity != tuple(prior.get(field) for field in ('package', 'version', 'language')):
            prior = {}
        path, theme, upstream_version, declared_overrides = upstream.get(package, ('', 'unmapped', '', ''))
        source_revision = revision if path else ''
        historical = history.get((package, extension['versionName']))
        if historical and extension['versionName'] != upstream_version:
            path, theme = historical['path'], historical['theme']
            source_revision, upstream_version = historical['revision'], historical['version']
            declared_overrides = '(historical revision)'
        sources[sid] = {
            'source_id': sid, 'package': package, 'version': extension['versionName'],
            'source': source['name'], 'language': source['lang'],
            'latest': int(source['supportsLatest']), 'configurable': int(source['isConfigurable']),
            'japan_route': int(source['japanRoute']), 'upstream_revision': source_revision,
            'upstream_path': path, 'upstream_version': upstream_version,
            'theme': theme, 'overrides': declared_overrides, 'adapter': prior.get('adapter', ''),
            **{key: prior.get(key, 'pending') for key in OPERATIONS}, 'evidence': prior.get('evidence', ''),
        }
        states = {sources[sid][key] for key in OPERATIONS}
        if not states <= STATES or states - {'pending'} and not sources[sid]['evidence']:
            raise ValueError(f'Invalid or unsupported migration status for {sid}')
    represented = {row['package'] for row in sources.values()}
    if missing := installed.keys() - represented:
        raise ValueError(f'Installed packages lack source IDs: {sorted(missing)}')
    if missing := previous.keys() - sources.keys():
        raise ValueError(f'Previously tracked IDs absent from current snapshot: {sorted(missing)}')
    return sorted(sources.values(), key=lambda row: (row['theme'], row['package'], int(row['source_id'])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('upstream_archive', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--history', type=Path, default=Path(__file__).resolve().parents[1] / 'docs/native-source-history.json')
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    previous = {}
    if args.output.is_file():
        with args.output.open(encoding='utf-8', newline='') as file:
            for row in csv.DictReader(file):
                if row['source_id'] in previous:
                    raise ValueError(f'Duplicate source ID in existing register: {row["source_id"]}')
                previous[row['source_id']] = row
    inventory = json.loads(args.inventory.read_text(encoding='utf-8-sig'))
    history = {(item['package'], item['version']): item for item in json.loads(args.history.read_text(encoding='utf-8'))}
    rows = make_rows(inventory, args.upstream_archive, previous, history)
    with args.output.open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len({row['package'] for row in rows})} packages, {len(rows)} source IDs")
    for name in OPERATIONS:
        print(name, dict(Counter(row[name] for row in rows)))
    if args.require_complete and any(row[key] not in {'verified', 'not_applicable'} for row in rows for key in OPERATIONS):
        raise SystemExit('Migration is incomplete')


if __name__ == '__main__':
    main()
