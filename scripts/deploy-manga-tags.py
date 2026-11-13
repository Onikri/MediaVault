#!/usr/bin/env python3
"""Validate installation defaults; live policy is managed only by the owner UI."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_tag_policy import Policy

def main():
    if '--validate' not in sys.argv:
        raise SystemExit('Repository deployment is retired. Use the owner control center: Управление контентом.')
    policy=Policy(json.loads(Path('server/manga-tag-policy.json').read_text(encoding='utf-8')))
    print('Validated',len(policy.rules),'canonical installation defaults; revision',policy.revision)

if __name__=='__main__':main()
