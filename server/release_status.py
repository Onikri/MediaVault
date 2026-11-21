"""Publication states shared by catalogue filters and title metadata."""

import json
from functools import lru_cache
from pathlib import Path

ALIASES = json.loads(Path(__file__).with_name('release-statuses.json').read_text(encoding='utf-8'))
STATES = tuple(ALIASES)
BY_ALIAS = {alias: state for state, aliases in ALIASES.items() for alias in aliases}


def code(value):
    if not isinstance(value, str):
        return ''
    return BY_ALIAS.get(value.strip().lower().replace('_', ' ').replace('-', ' '), '')


def work_status(records):
    present = {code(row.get('status')) for row in records}
    return next((state for state in STATES if state in present), '')


@lru_cache(maxsize=4)
def _expression(document):
    raw = f"json_extract({document},'$.status')"
    value = f"lower(trim(replace(replace({raw},'_',' '),'-',' ')))"
    cases = []
    for state, aliases in ALIASES.items():
        # SQLite lower() folds ASCII. Match the common casing of source labels
        # in Cyrillic with literals so the same expression can be indexed.
        forms = sorted({form for alias in aliases for form in (alias, alias.capitalize(), alias.upper())})
        literals = ','.join("'" + form.replace("'", "''") + "'" for form in forms)
        cases.append(f"WHEN {value} IN ({literals}) THEN '{state}'")
    return 'CASE ' + ' '.join(cases) + " END", raw


def initialize_index(db, *, table, document, work, kind=''):
    expression, raw = _expression(document)
    prefix = kind+',' if kind else ''
    db.execute(f"CREATE INDEX IF NOT EXISTS {table}_release_status_v1 ON {table}({prefix}{expression},{work}) WHERE {raw} IS NOT NULL")


def condition(status, *, table, document, work, peer_work, kind=''):
    if not status:
        return '', []
    if status not in (*STATES,'available'):
        from fastapi import HTTPException
        raise HTTPException(422, 'Неизвестный статус выпуска.')
    expression, raw = _expression('peer.'+document)
    prefix = 'peer.kind=? AND ' if kind else ''
    scope = [kind] if kind else []
    select = f"SELECT {peer_work} FROM {table} peer WHERE {prefix}{raw} IS NOT NULL AND {expression}"
    if status=='available':
        if table=='catalog_titles':
            # The large manga index already has numeric years and chapter counts.
            # Only materialize the small set of explicitly announced works.
            return (f"COALESCE(t.year,0)<=CAST(strftime('%Y','now') AS INTEGER) AND "
                    f"(t.chapter_count>0 OR (t.chapter_count IS NULL AND {work} NOT IN ({select}='anons')))"),scope
        data='peer.'+document
        year=f"CAST(json_extract({data},'$.year') AS INTEGER)"
        start=f"substr(json_extract({data},'$.startDate'),1,10)"
        this_year="CAST(strftime('%Y','now') AS INTEGER)"
        not_future=f"COALESCE({year},0)<={this_year} AND substr(COALESCE({start},''),1,7)<=strftime('%Y-%m','now') AND COALESCE(date({start}),date('now'))<=date('now')"
        eligible=f"{not_future} AND COALESCE({expression},'')<>'anons'"
        if kind in {'anime','tv','movie'}:
            aired=f"CAST(json_extract({data},'$.episodesAired') AS INTEGER)"
            # Episode totals describe the plan. Only a broadcast, a past
            # premiere or known completion count as evidence of release.
            first=f"CAST(json_extract({data},'$.firstAiringAt') AS INTEGER)"
            eligible+=f""" AND ({expression}='released' OR {first} BETWEEN 1 AND unixepoch()
                OR {aired}>0 OR (COALESCE({aired},1)>0 AND (
                date({start})<date('now') OR (length({start})=7 AND {start}<strftime('%Y-%m','now'))
                OR {year} BETWEEN 1 AND {this_year}-1
            )))"""
        return f"{work} IN (SELECT {peer_work} FROM {table} peer WHERE {prefix}{eligible})",scope
    clause = f"{work} IN ({select}=?)"
    params = [*scope,status]
    higher = STATES[:STATES.index(status)]
    if higher:
        clause += f" AND {work} NOT IN ({select} IN ({','.join('?' for _ in higher)}))"
        params.extend([*scope,*higher])
    return clause, params
