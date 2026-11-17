"""Record live probe results in the migration register and the activation list.

Reads JSON lines written by ``probe-native-source-batch.py --search --chapters
--pages`` (later files override earlier ones for the same ID). A profile is
activated only when catalogue, exact search, chapter list, page list and the
first image (fetched the way the reader and CBZ export fetch it) all passed.
"""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / 'docs/native-source-inventory.csv'
ACTIVATION = ROOT / 'server/manga_native_activation.json'
LIVE = ('search', 'catalogue', 'metadata', 'chapters', 'pages')
# Sources whose current route carries more than the direct adapter does:
# manga_discovery searches them with the owner's Lib session, the Russian
# alias resolution for MangaDex or their own dedicated search modules.
HOLD_NAMES = frozenset({'MangaLib', 'HentaiLib', 'SlashLib', 'MangaDex', 'Senkognito', 'HentaiChan', 'HenChan',
                        'HentaiChan.cc', 'Hitomi', 'HManga', 'ReManga', 'Remanga'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', nargs='+', type=Path)
    parser.add_argument('--evidence', default='native-source-verification.md#активация-прямых-источников')
    args = parser.parse_args()
    final = {}
    for path in args.results:
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('event') == 'source':
                final[row['source_id']] = row
    passed = {sid for sid, row in final.items()
              if row.get('status') == 'passed' and row.get('search') and row.get('chapters') and row.get('pages')}
    with REGISTER.open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        if row['source_id'] in passed:
            for key in LIVE:
                row[key] = 'verified'
            if row['evidence'] in {'', 'pending'}:
                row['evidence'] = args.evidence
    with REGISTER.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    known = {row['source_id'] for row in rows if row['source'] not in HOLD_NAMES}
    try:
        current = set(json.loads(ACTIVATION.read_text(encoding='utf-8'))['sourceIds'])
    except (OSError, ValueError, KeyError):
        current = set()
    listed = sorted((current | passed) & known)
    ACTIVATION.write_text(json.dumps({'checkedAt': date.today().isoformat(), 'sourceIds': listed}, indent=0) + '\n',
                          encoding='utf-8')
    print(json.dumps({'probed': len(final), 'passed': len(passed), 'activated': len(listed)}))


if __name__ == '__main__':
    main()
