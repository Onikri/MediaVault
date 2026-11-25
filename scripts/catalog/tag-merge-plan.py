"""Build an additive tag policy from the reviewed B1 merge groups.

Only merges (aliases added to an owner rule or a new canonical rule) and the
owner-approved reversible hiding of listed labels are produced. No rule,
alias, exclusion or source fact is removed.

  python scripts/catalog/tag-merge-plan.py --b1 DIR --live live-policy.json --out DIR
"""
import argparse, collections, csv, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from manga_tag_policy import Policy, normalize, discovered_identity  # noqa: E402
from catalog_taxonomy import classify  # noqa: E402
from tag_merge import additive_problems  # noqa: E402

# Members of one B1 group that may mean something different.
REJECT = {
    'Art': '«Arts» может значить искусства вообще или боевые искусства, «Art» — рисунок',
    'Athletics': '«Athletic» — телосложение персонажа, «Athletics» — лёгкая атлетика',
    'BOMB': '«BOMB» — название журнала (BOMB!), а не бомбы',
    'Chaos': '«Chao» — существо из Sonic, не «хаос»',
    'Doom': '«Dom» — доминант в BDSM, не «Doom»',
    'Fans': '«Fan» бывает веером, «Fans» — поклонники',
    'Korean': '«korean» — происхождение/язык работы, «Koreans» — персонажи-корейцы',
    'Americans': '«American» — происхождение работы, «Americans» — персонажи',
    'Germans': '«German» — язык/происхождение, «Germans» — персонажи',
    'Elemental': '«elemental» — стихийная магия, «Elementals» — существа-элементали',
    'Charms': '«Charm» — обаяние, «Charms» — амулеты',
    'Clubs': '«Clubs» — школьные клубы, «Club» у других источников — ночной клуб',
    'Morts': '«Mort» — имя персонажа, не множественное число',
    'Moose': '«mouse» — мышь, не лось',
    'Pieces': '«piece» неоднозначно (фандом One Piece, «часть»)',
    'Powers': '«Power» — имя персонажа (Chainsaw Man), не «способности»',
    'Rule 63': '«Rules» — «правила», не «Rule 63»',
    'Shorts': '«Shorts» — одежда, «Short» — короткая история',
    'Souls': '«SoL» — Slice of Life, не «души»',
    'Sweet': '«Sweet» — настроение истории, «Sweets» — сладости',
    "Teens' Love": "«Teens' Love» — отдельный жанр TL, «Teen Love» — подростковая романтика",
    'Trap': '«Trap» — сленг о персонаже, «Traps» — ловушки',
    'Yuki': 'Yuki и Yuuki — разные японские имена',
    'Kyoka': 'Kyoka и Kyouka могут быть разными именами',
    'Ships': '«Ship» — шиппинг в фандоме, «Ships» — корабли',
}
EXCLUDE = {'Pool': {'Pol': '«Pol» — политика/Польша, не бассейн'}}
ACCEPT_NOTE = {
    'Групповой секс': '«Group» у nhentai/3hentai/chaika/simply-hentai — тег группового секса (не кружок)',
}
HIDE_TYPES = ('title-leak', 'vocab-only', 'nowhere', 'no-letters')


def write_csv(path, header, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle, delimiter=';')
        writer.writerow(header)
        writer.writerows(rows)


def cyrillic(text):
    return bool(re.search('[а-яё]', text.casefold()))


def clean_name(name):
    return re.sub(r'\s+\d{1,9}$', '', name).strip()


def category_of(policy, label):
    value = classify(label, 'tags', 'manga', policy)
    return value[0] if value else ''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--b1', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    b1, out = Path(args.b1), Path(args.out)
    live = json.loads(Path(args.live).read_text(encoding='utf-8'))
    old = Policy(live)
    owner = {row['key']: row for row in live['tags']}
    owner_token = {}
    for row in live['tags']:
        for value in [row['key'], row['label'], *row['aliases']]:
            owner_token[normalize(value)] = row['key']
    groups = json.loads((b1 / 'merge-groups.json').read_text(encoding='utf-8'))

    data = json.loads(json.dumps(live))
    rules = {row['key']: row for row in data['tags']}
    plan, accepted, diff = [], [], []
    for group in groups:
        name = group['proposed_name']
        members = list(dict.fromkeys(m['label'] for m in group['members']))
        works = {}
        for m in group['members']:
            works[(m['kind'], old.identity(m['label']))] = m['works']
        before = sum(works.values())
        if name in REJECT:
            plan.append(['reject', name, ' | '.join(members), '', before, REJECT[name]])
            continue
        notes = []
        for label, reason in EXCLUDE.get(name, {}).items():
            if label in members:
                members.remove(label)
                notes.append('исключён ' + label + ': ' + reason)
        owners = list(dict.fromkeys(owner_token[t] for v in members if (t := normalize(v)) in owner_token))
        if len(owners) > 1:
            keep = owners[0]
            dropped = [v for v in members if owner_token.get(normalize(v), keep) != keep]
            members = [v for v in members if v not in dropped]
            notes.append('другие правила владельца не сливаются: ' + ', '.join(dropped))
        if len({normalize(v) for v in members}) < 2 and not owners:
            plan.append(['reject', name, ' | '.join(members), '', before, 'после исключений остался один вариант; ' + '; '.join(notes)])
            continue
        if owners:
            key = owners[0]
            canonical = owner[key]['label']
        else:
            if group['group'].startswith('g:') or cyrillic(name):
                canonical = name
                key = normalize(name)
            else:
                canonical = clean_name(name)
                spellings = [v for v in members if normalize(v) == normalize(canonical)]
                if spellings:
                    # Prefer a real source spelling in title case ("Body Modification").
                    canonical = max(spellings, key=lambda v: (sum(w[:1].isupper() for w in v.split()), v == canonical))
                weights = collections.Counter()
                for m in group['members']:
                    if m['label'] in members:
                        weights[old.identity(m['label'])] += m['works']
                key = weights.most_common(1)[0][0]
                if normalize(canonical) != key and normalize(canonical) in {normalize(v) for v in members}:
                    key = normalize(canonical)
        reason = 'одно понятие: ' + group['rationale']
        if name in ACCEPT_NOTE:
            reason += '; ' + ACCEPT_NOTE[name]
        if notes:
            reason += '; ' + '; '.join(notes)
        plan.append(['accept', canonical, ' | '.join(members), key if key in owner else '', before, reason])
        accepted.append({'name': name, 'canonical': canonical, 'key': key, 'members': members, 'owner': key in owner,
                         'works': works})
        if key in rules:
            row = rules[key]
            known = {normalize(v) for v in [row['key'], row['label'], *row['aliases']]}
            added = [v for v in members if normalize(v) not in known and not known.add(normalize(v))]
            if len(row['aliases']) + len(added) > 120:
                raise SystemExit('alias limit for ' + key)
            row['aliases'].extend(added)
            if added:
                diff.append('+ алиасы → «' + row['label'] + '» [' + key + ']: ' + ', '.join(added))
        else:
            known = {key, normalize(canonical)}
            aliases = [v for v in members if normalize(v) not in known and not known.add(normalize(v))]
            row = {'key': key, 'label': canonical, 'aliases': aliases}
            heavy = max((m for m in group['members'] if m['label'] in members), key=lambda m: m['works'])
            if category_of(old, heavy['label']) == 'genres':
                row['category'] = 'genre'
            data['tags'].append(row)
            rules[key] = row
            diff.append('+ правило «' + canonical + '» [' + key + ']' + (' (genre)' if row.get('category') else '') + ': ' + ', '.join(aliases))

    merged = Policy(data)

    # Reversible hiding of the four owner-approved B1 classes.
    labels = collections.defaultdict(int)
    with open(b1 / 'tags.csv', encoding='utf-8-sig') as handle:
        for row in csv.DictReader(handle, delimiter=';'):
            labels[row['label']] += int(row['works'] or 0)
    with open(b1 / 'approval.csv', encoding='utf-8-sig') as handle:
        candidates = [r for r in csv.DictReader(handle, delimiter=';') if r['item_type'] in HIDE_TYPES]
    protected = set(owner)
    for item in accepted:
        protected.add(item['key'])
        protected.update(old.identity(v) for v in item['members'])
        protected.update(normalize(v) for v in item['members'])
    protected.update(k for k in merged.rules if k not in merged.hidden)
    hide_norms = {normalize(r['label']) for r in candidates}
    hidden_of = lambda v: merged.aliases.get(normalize(v), discovered_identity(v))
    by_key = collections.defaultdict(list)
    for r in candidates:
        by_key[hidden_of(r['label'])].append(r['label'])
    collateral = collections.defaultdict(list)
    for label, count in labels.items():
        if normalize(label) in hide_norms or not count:
            continue
        for token in {normalize(label), merged.identity(label)}:
            for culprit in by_key.get(token, []):
                collateral[culprit].append(label)
    hide, skipped = [], []
    for r in candidates:
        label, kind = r['label'], r['item_type']
        key = hidden_of(label)
        if not normalize(label):
            skipped.append([label, kind, 'нормализованный ключ пуст']); continue
        if key in protected or normalize(label) in protected:
            skipped.append([label, kind, 'ключ «' + key + '» совпадает с правилом или группой объединения']); continue
        if collateral.get(label):
            skipped.append([label, kind, 'скрыл бы другие метки с тайтлами: ' + ', '.join(collateral[label][:5])]); continue
        hide.append([label, kind, r['reason']])
    data['hiddenTags'] = list(dict.fromkeys([*data.get('hiddenTags', []), *(row[0] for row in hide)]))
    new = Policy(data)

    # Verification: only accepted members change identity, to their canonical key.
    problems = additive_problems(live, data)
    allowed = {}
    for item in accepted:
        for v in item['members']:
            allowed[normalize(v)] = item['key']
            allowed[discovered_identity(v)] = item['key']
    universe = set(labels) | {v for row in live['tags'] for v in [row['key'], row['label'], *row['aliases']]}
    changed, category_changes = 0, []
    for label in universe:
        a, b = old.identity(label), new.identity(label)
        if a != b:
            changed += 1
            if b != allowed.get(normalize(label), allowed.get(discovered_identity(label))):
                problems.append('неожиданная смена ключа: ' + label + ' ' + a + ' → ' + b)
        ca, cb = category_of(old, label), category_of(new, label)
        if ca != cb and labels.get(label):
            category_changes.append(label + ': ' + ca + ' → ' + cb)
    for item in accepted:
        if item['key'] in new.hidden:
            problems.append('группа стала скрытой: ' + item['canonical'])
        if len({new.identity(v) for v in item['members']}) != 1:
            problems.append('группа не сошлась в один ключ: ' + item['canonical'])
    for key in owner:
        if new.identity(key) != old.identity(key) or old.identity(key) in new.hidden and old.identity(key) not in old.hidden:
            problems.append('правило владельца изменилось или скрыто: ' + key)
    if set(old.redirects.items()) - set(new.redirects.items()):
        problems.append('пропали перенаправления таксономии')
    visible_old = {k for k in old.rules if k not in old.hidden}
    visible_new = {k for k in new.rules if k not in new.hidden}
    lost = visible_old - visible_new
    hidden_keys = {hidden_of(row[0]) for row in hide}
    if lost - hidden_keys:
        problems.append('пропали видимые правила: ' + ', '.join(sorted(lost - hidden_keys)[:20]))

    # Affected works estimate (members whose key moves to the canonical one).
    moved = 0
    for item in accepted:
        moved += sum(w for (kind, k), w in item['works'].items() if k != item['key'])

    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / 'merge-plan.csv', ['decision', 'canonical', 'members', 'existing_rule_key', 'works_before', 'reason'], plan)
    write_csv(out / 'hide-list.csv', ['label', 'item_type', 'reason'], hide)
    write_csv(out / 'hide-skipped.csv', ['label', 'item_type', 'reason'], skipped)
    (out / 'new-policy.json').write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    counts = collections.Counter(row[0] for row in plan)
    new_rules = len(data['tags']) - len(live['tags'])
    added_aliases = sum(len(r['aliases']) for r in data['tags']) - sum(len(r['aliases']) for r in live['tags'])
    summary = [
        'Только добавления. Старая ревизия ' + old.revision + ', новая ' + new.revision,
        'Группы: принято ' + str(counts['accept']) + ', отклонено ' + str(counts['reject']),
        'Правил: было ' + str(len(live['tags'])) + ', новых ' + str(new_rules) + '; алиасов добавлено ' + str(added_aliases)
        + ' (у правил владельца ' + str(sum(1 for a in accepted if a['owner'])) + ' групп)',
        'Скрыто меток: ' + str(len(hide)) + ' ' + str(dict(collections.Counter(r[1] for r in hide)))
        + '; пропущено ' + str(len(skipped)) + ' ' + str(dict(collections.Counter(r[1] for r in skipped))),
        'Меток со сменой ключа: ' + str(changed) + '; работ с переносом ключа ≈ ' + str(moved),
        'Смена категории (genre/tag) у меток с тайтлами: ' + str(len(category_changes)),
        *('  ' + v for v in category_changes[:40]),
        'Видимых правил: было ' + str(len(visible_old)) + ', стало ' + str(len(visible_new)),
        'Проверки: ' + ('OK' if not problems else 'ОШИБКИ ' + str(len(problems))),
        *('  ! ' + p for p in problems[:60]),
        '', *diff,
    ]
    (out / 'policy-diff.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    print('\n'.join(summary[:9 + min(len(category_changes), 40)]))
    print('problems', len(problems))
    for p in problems[:30]:
        print(' !', p[:200])
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
