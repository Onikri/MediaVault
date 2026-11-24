#!/usr/bin/env python3
"""Compile canonical work/tag indexes for an existing MediaVault catalogue.

This is intentionally offline and metadata-only: it reads retained source
facts, rewrites derived taxonomy rows, and builds compact work-level lookup
tables. It never contacts a source or downloads covers/pages.
"""
import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))


def default_database():
    return Path(os.getenv('DATA_DIR',ROOT/'.codex-local'/'data'))/'manga-discovery.sqlite'


def percentile(values,portion):
    if not values:return 0.0
    ordered=sorted(values)
    return ordered[min(len(ordered)-1,round((len(ordered)-1)*portion))]


def benchmark(db,repetitions):
    samples=db.execute('''SELECT category,tag_key FROM catalog_tag_stats
                          ORDER BY works DESC LIMIT 12''').fetchall()
    content=db.execute('''SELECT kind,category,tag_key FROM content_tag_stats
                          ORDER BY works DESC LIMIT 12''').fetchall()
    timings=[]
    for _ in range(repetitions):
        for category,key in samples:
            started=time.perf_counter()
            db.execute('''SELECT work_key FROM catalog_work_tags
                          WHERE category=? AND tag_key=? LIMIT 60''',(category,key)).fetchall()
            timings.append((time.perf_counter()-started)*1000)
        for kind,category,key in content:
            started=time.perf_counter()
            db.execute('''SELECT work_key FROM content_work_tags
                          WHERE kind=? AND category=? AND tag_key=? LIMIT 60''',(kind,category,key)).fetchall()
            timings.append((time.perf_counter()-started)*1000)
    return {'queries':len(timings),'p50Ms':round(statistics.median(timings),3) if timings else 0,
            'p95Ms':round(percentile(timings,.95),3),'maxMs':round(max(timings),3) if timings else 0}


def main():
    parser=argparse.ArgumentParser(description='Compile MediaVault canonical catalogue indexes')
    parser.add_argument('--database',type=Path,default=default_database())
    parser.add_argument('--force',action='store_true',help='rebuild even if revision markers are current')
    parser.add_argument('--benchmark',type=int,default=10,metavar='REPETITIONS')
    args=parser.parse_args()
    if not args.database.is_file():parser.error('database does not exist: '+str(args.database))

    from manga_catalog_index import initialize as initialize_manga
    from content_catalog import initialize as initialize_content

    started=time.perf_counter()
    db=sqlite3.connect(args.database,timeout=120)
    try:
        db.execute('PRAGMA busy_timeout=120000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('PRAGMA temp_store=MEMORY')
        with db:
            if args.force:
                tables={name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'catalog_policy_state' in tables:
                    db.execute("DELETE FROM catalog_policy_state WHERE name IN ('revision','label-index','work-tag-index')")
                if 'content_catalog_state' in tables:
                    db.execute("DELETE FROM content_catalog_state WHERE name IN ('policy','label-index','work-tag-index')")
            initialize_manga(db)
            initialize_content(db)
        db.execute('ANALYZE catalog_work_tags')
        db.execute('ANALYZE content_work_tags')
        db.execute('PRAGMA optimize')
        summary={
            'database':str(args.database.resolve()),
            'seconds':round(time.perf_counter()-started,3),
            'sourceTitles':db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0],
            'contentTitles':db.execute('SELECT COUNT(*) FROM content_titles').fetchone()[0],
            'mangaWorkTags':db.execute('SELECT COUNT(*) FROM catalog_work_tags').fetchone()[0],
            'contentWorkTags':db.execute('SELECT COUNT(*) FROM content_work_tags').fetchone()[0],
            'canonicalTags':db.execute('SELECT COUNT(*) FROM catalog_tag_stats').fetchone()[0]
                            +db.execute('SELECT COUNT(*) FROM content_tag_stats').fetchone()[0],
            'benchmark':benchmark(db,max(0,min(100,args.benchmark))),
        }
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    finally:
        db.close()


if __name__=='__main__':main()
