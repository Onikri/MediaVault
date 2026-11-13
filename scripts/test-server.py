"""Run server behavior contracts against neutral, stable taxonomy fixtures.

The editable production policy is validated separately by deploy-manga-tags.py.
Removing a legitimate tag must not invalidate a parser's fixture expectations.
"""
from pathlib import Path
import os,sys,unittest
root=Path(__file__).resolve().parents[1]
os.environ.setdefault('MANGA_TAG_POLICY_FILE',str(root/'tests/fixtures/manga-tag-policy.json'))
sys.path.insert(0,str(root/'server'))
suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_*.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
