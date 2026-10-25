"""Exercise deployment orchestration with a real private-data backup and fake Docker."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'deploy/oracle/update-existing.sh'
REVISION='a'*40


class ExistingUpdateTests(unittest.TestCase):
    def exercise(self,root,*,active=False,health_failure=False):
        work=root/'legacy/media-vault/deploy/oracle';data=work/'data';data.mkdir(parents=True)
        for name,value in [('.env','private-fixture'),('compose.yaml','services: {}'),('release-v51.yaml','services: {}'),('Caddyfile','fixture')]:
            (work/name).write_text(value)
        (data/'service.key').write_bytes(b'private-fixture-key')
        with sqlite3.connect(data/'tasks.sqlite') as db:
            db.executescript('CREATE TABLE tasks (status TEXT); CREATE TABLE settings (name TEXT,value BLOB);')
            db.execute('INSERT INTO tasks VALUES (?)',('running' if active else 'done',))
            db.execute('INSERT INTO settings VALUES (?,?)',('oauth-fixture',b'encrypted-fixture'))
        files=[str(work/'compose.yaml'),str(work/'release-v51.yaml')]
        old={'Id':'old','Image':'sha256:old','Config':{'Labels':{
            'com.docker.compose.service':'importer','com.docker.compose.project':'oracle',
            'com.docker.compose.project.working_dir':str(work),
            'com.docker.compose.project.config_files':','.join(files)}},
            'Mounts':[{'Destination':'/data','Source':str(data),'Type':'bind'}]}
        calls=[]
        def output(args,**kwargs):
            calls.append(args)
            if args==['docker','ps','-q']:return 'old'
            if args[:2]==['docker','inspect']:return json.dumps([old])
            if args[0]=='git':
                if 'get-url' in args:return 'https://github.com/Onikri/MediaVault.git'
                if 'status' in args:return ''
                if 'rev-parse' in args:return REVISION
            if args[:3]==['docker','exec','old']:return json.dumps({'application':'MediaVault','version':5,'oauthConfigured':True})
            if args[:2]==['docker','compose']:
                if 'ps' in args:return 'new'
                if 'exec' in args:
                    if not any('release-'+REVISION[:12] in arg for arg in args):return json.dumps({'application':'MediaVault','version':5,'oauthConfigured':True})
                    if health_failure:raise subprocess.CalledProcessError(1,args)
                    return json.dumps({'application':'MediaVault','version':6,'voiceDiscovery':True,'oauthConfigured':True})
            raise AssertionError(args)
        def run(args,**kwargs):calls.append(args)
        code=SCRIPT.read_text().split("python3 - \"$revision\" <<'PY'\n",1)[1].rsplit('\nPY',1)[0]
        # Relocate only host deployment directories into this isolated fixture.
        code=code.replace("'/opt/mediavault-releases'",repr(str(root/'releases'))).replace("'/opt/mediavault-backups'",repr(str(root/'backups'))).replace("'/var/tmp/mediavault-update-'",repr(str(root/'update-')))
        try:
            with patch.object(sys,'argv',['update',REVISION]),patch('subprocess.check_output',side_effect=output),patch('subprocess.run',side_effect=run),patch('time.sleep'),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                exec(compile(code,str(SCRIPT),'exec'),{})
        except BaseException as error:return work,data,files,calls,error
        return work,data,files,calls,None

    def test_nested_legacy_compose_retains_all_overrides_and_private_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work,data,files,calls,error=self.exercise(root)
            self.assertIsNone(error)
            up=next(c for c in calls if c[:2]==['docker','compose'] and 'up' in c)
            self.assertIn('--no-build',up);self.assertIn('--no-deps',up)
            for file in files:self.assertIn(file,up)
            self.assertIn(str(work/('release-'+REVISION[:12]+'.yaml')),up)
            self.assertEqual((work/'.env').read_text(),'private-fixture')
            self.assertEqual((data/'service.key').read_bytes(),b'private-fixture-key')
            archive=next((root/'backups').glob('*/private-data.tar.gz'))
            self.assertEqual(archive.stat().st_mode&0o777,0o600)
            with tarfile.open(archive) as saved:
                self.assertEqual(saved.extractfile('data/service.key').read(),b'private-fixture-key')
                self.assertIn('data/tasks.sqlite',saved.getnames())
            self.assertFalse(any(c[0]=='git' and str(root/'legacy') in ' '.join(c) for c in calls))

    def test_active_import_refuses_build_stop_and_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            *_,calls,error=self.exercise(Path(directory),active=True)
            self.assertIsInstance(error,SystemExit)
            self.assertFalse(any('build' in c or 'stop' in c or 'up' in c for c in calls))

    def test_failed_health_restores_original_compose_without_new_override(self):
        with tempfile.TemporaryDirectory() as directory:
            work,data,files,calls,error=self.exercise(Path(directory),health_failure=True)
            self.assertIsInstance(error,RuntimeError)
            ups=[c for c in calls if c[:2]==['docker','compose'] and 'up' in c]
            self.assertEqual(len(ups),2)
            for file in files:self.assertIn(file,ups[-1])
            self.assertNotIn(str(work/('release-'+REVISION[:12]+'.yaml')),ups[-1])
            self.assertEqual((data/'service.key').read_bytes(),b'private-fixture-key')
