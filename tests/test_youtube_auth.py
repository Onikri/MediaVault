"""Owner session storage and temporary yt-dlp files; all cookies are fixtures."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from task_store import TaskStore
import youtube_auth as auth
import music_audio as music
import online_sessions as online
COOKIE='# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tfixture-youtube-session\n'

class YouTubeAuth(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup);self.store=TaskStore(self.temporary.name);self.addCleanup(self.store.database.close)
  old=auth._store;self.addCleanup(setattr,auth,'_store',old)
  self.app=FastAPI();auth.install(self.app,lambda:'owner',lambda:self.store);self.client=TestClient(self.app);music.cache.clear();online.sessions.clear()
 def test_status_never_exports_credentials_and_storage_is_encrypted(self):
  self.assertFalse(self.client.get('/music/youtube/session').json()['configured'])
  result=self.client.put('/music/youtube/session',json={'cookies':COOKIE});self.assertEqual(result.status_code,200);self.assertNotIn('fixture-youtube-session',result.text)
  self.assertTrue(self.client.get('/music/youtube/session').json()['configured']);self.assertEqual(auth.cookie_text(),COOKIE)
  raw=self.store.database.execute('SELECT value FROM settings WHERE name=?',(auth.SETTING,)).fetchone()[0];self.assertNotIn(b'fixture-youtube-session',raw)
 def test_rotated_cookie_diagnostic_preserves_credentials_and_exposes_no_values(self):
  self.client.put('/music/youtube/session',json={'cookies':COOKIE})
  self.assertTrue(auth.cookie_rejected('WARNING: The provided YouTube account cookies are no longer valid.'))
  auth.playback_rejected(auth.credentials())
  status=self.client.get('/music/youtube/session').json()
  self.assertTrue(status['needsRefresh']);self.assertNotIn('private-value',json.dumps(status))
  self.assertEqual(auth.cookie_text(),COOKIE)
  self.client.put('/music/youtube/session',json={'cookies':COOKIE})
  self.assertFalse(self.client.get('/music/youtube/session').json()['needsRefresh'])
 def test_only_youtube_cookies_are_kept(self):
  raw=COOKIE+'.google.com\tTRUE\t/\tTRUE\t0\tSID\tfixture-unrelated-google-session\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tfixture-http-only\n'
  normalized=auth.normalize_cookies(raw);self.assertNotIn('fixture-unrelated-google-session',normalized);self.assertIn('fixture-http-only',normalized)
 def test_invalid_expired_and_non_session_exports_are_rejected(self):
  for raw in ['',COOKIE.replace('Netscape','Other'),COOKIE.replace('\t0\t','\t1\t'),COOKIE.replace('.youtube.com','.youtube.com.evil'),COOKIE.replace('SAPISID','VISITOR_INFO1_LIVE'),'x'*(1024*1024+1)]:
   with self.assertRaises(HTTPException):auth.normalize_cookies(raw)
 def test_upload_and_delete_revoke_old_audio_and_clear_cache(self):
  music.cache['old']=True;token,s=online.create('owner',{},'music');other,_=online.create('other',{},'music');epoch=music.auth_epoch
  self.assertEqual(self.client.put('/music/youtube/session',json={'cookies':COOKIE}).status_code,200);self.assertEqual(music.cache,{});self.assertNotIn(token,online.sessions);self.assertIn(other,online.sessions);self.assertGreater(music.auth_epoch,epoch)
  self.assertEqual(self.client.delete('/music/youtube/session').json(),{'configured':False,'updated':None});self.assertFalse(auth.cookie_text())
 def test_anonymous_cannot_read_upload_or_remove_session(self):
  def denied():raise HTTPException(401,'Login')
  app=FastAPI();auth.install(app,denied,lambda:self.store);client=TestClient(app)
  for method in ['get','put','delete']:
   response=getattr(client,method)('/music/youtube/session',**({'json':{'cookies':COOKIE}} if method=='put' else {}));self.assertEqual(response.status_code,401)
  self.assertIsNone(self.store.setting(auth.SETTING))
 def test_extractor_uses_private_temporary_cookie_copy_not_browser_credentials(self):
  paths=[];expiry=int(time.time())+3600
  def spawn(command,**kwargs):
   cookie=Path(command[command.index('--cookies')+1]);paths.append(cookie);self.assertEqual(cookie.read_text(),COOKIE);self.assertNotIn('fixture-youtube-session',' '.join(command));self.assertNotIn('--cookies-from-browser',command)
   if os.name!='nt':self.assertEqual(cookie.stat().st_mode&0o777,0o600)
   kwargs['stdout'].write(json.dumps({'id':'dQw4w9WgXcQ','title':'Fixture','duration':213,'url':'https://media.googlevideo.com/videoplayback?expire='+str(expiry),'ext':'m4a','vcodec':'none','protocol':'https','http_headers':{'Cookie':'fixture-secret-header'}}).encode());kwargs['stdout'].flush();p=MagicMock();p.poll.return_value=0;p.returncode=0;return p
  self.client.put('/music/youtube/session',json={'cookies':COOKIE})
  with patch.dict(os.environ,{'DATA_DIR':self.temporary.name}),patch.object(music,'audio_url',side_effect=lambda u:u),patch.object(music,'verify_audio'),patch.object(music.subprocess,'Popen',side_effect=spawn):data,_=music.extract('dQw4w9WgXcQ',True)
  self.assertNotIn('Cookie',data['headers']);self.assertTrue(paths);self.assertFalse(paths[0].exists());self.assertEqual(list((Path(self.temporary.name)/'temporary').iterdir()),[])
 def test_published_pages_can_preflight_session_upload_but_other_origins_cannot(self):
  import api
  client=TestClient(api.app)
  headers={'Origin':api.ORIGIN,'Access-Control-Request-Method':'PUT','Access-Control-Request-Headers':'authorization,content-type'}
  response=client.options('/music/youtube/session',headers=headers);self.assertEqual(response.status_code,200);self.assertIn('PUT',response.headers['access-control-allow-methods'])
  response=client.options('/music/youtube/session',headers={**headers,'Origin':'https://untrusted.example'});self.assertEqual(response.status_code,400)

 def test_late_diagnostic_cannot_reject_a_new_manual_session(self):
  self.client.put('/music/youtube/session',json={'cookies':COOKIE});old=auth.credentials()
  self.store.setting(auth.SETTING,{**old,'updated':old['updated']+1})
  auth.playback_rejected(old)
  self.assertFalse(self.client.get('/music/youtube/session').json()['needsRefresh'])
 def test_provider_rotation_is_saved_but_cannot_replace_a_new_jar(self):
  self.client.put('/music/youtube/session',json={'cookies':COOKIE});old=auth.credentials()
  # Use the same valid cookie names with a changed supplied value.
  lines=COOKIE.splitlines();parts=lines[-1].split('\t');parts[-1]='provider-refreshed-session';lines[-1]='\t'.join(parts);changed='\n'.join(lines)+'\n'
  auth.playback_verified(changed,old);self.assertIn('provider-refreshed-session',auth.cookie_text())
  self.store.setting(auth.SETTING,{**old,'updated':old['updated']+1})
  auth.playback_verified(changed,old);self.assertEqual(auth.cookie_text(),COOKIE)

 def test_success_failure_success_never_persists_a_rejected_jar(self):
  login = '.youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tfixture-login\n'
  original = COOKIE + login
  rotated = original.replace('fixture-youtube-session', 'fixture-rotated-session')
  self.client.put('/music/youtube/session', json={'cookies': original})
  expired = COOKIE.replace('fixture-youtube-session', 'fixture-invalid-session')
  inputs = []
  anonymous = {'ok': True}
  def spawn(command, **kwargs):
   video_id = command[-1].split('=')[-1]
   result = MagicMock()
   data = {'id':video_id, 'title':'Fixture', 'duration':180, 'ext':'m4a', 'vcodec':'none',
           'protocol':'https', 'url':'https://media.googlevideo.com/videoplayback'}
   if '--cookies' not in command:
    inputs.append(None)
    if anonymous['ok']:
     kwargs['stdout'].write(json.dumps(data).encode());result.returncode = 0
    else:
     kwargs['stderr'].write(b'ERROR: Sign in to confirm you are not a bot');result.returncode = 1
    result.poll.return_value = result.returncode
    return result
   cookie = Path(command[command.index('--cookies')+1])
   inputs.append(cookie.read_text())
   if len([v for v in inputs if v]) == 2:
    cookie.write_text(expired)
    kwargs['stderr'].write(b'WARNING: The provided YouTube account cookies are no longer valid.\n')
    result.returncode = 1
   else:
    cookie.write_text(rotated)
    kwargs['stdout'].write(json.dumps(data).encode())
    result.returncode = 0
   result.poll.return_value = result.returncode
   return result
  with patch.dict(os.environ, {'DATA_DIR':self.temporary.name}), patch.object(music, 'audio_url', side_effect=lambda value:value), patch.object(music, 'verify_audio'), patch.object(music.subprocess, 'Popen', side_effect=spawn):
   music.extract('dQw4w9WgXcQ', True)
   self.assertEqual(auth.cookie_text(), rotated)
   # Revoked cookies: the same record is fetched anonymously instead of failing.
   music.extract('tRwHpyOq4P4', True)
   self.assertTrue(auth.credentials()['needsRefresh'])
   self.assertEqual(auth.cookie_text(), rotated)
   # A revoked session is not sent first; anonymous playback suffices.
   music.extract('abcdefghijk', True)
   self.assertEqual(inputs, [original, rotated, None, None])
   # When YouTube wants a sign-in, the stale session is still tried and recovers.
   anonymous['ok'] = False
   music.extract('ABCDEFGHIJK', True)
  self.assertEqual(inputs, [original, rotated, None, None, None, rotated])
  self.assertFalse(auth.credentials()['needsRefresh'])
  self.assertEqual(auth.cookie_text(), rotated)

if __name__=='__main__':unittest.main()
