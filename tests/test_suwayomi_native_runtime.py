import copy,importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('native_runtime',Path(__file__).resolve().parents[1]/'deploy/oracle/enable-suwayomi-native.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
class NativeRuntimeTests(unittest.TestCase):
 def test_private_executable_jni_tmpfs_preserves_original_runtime_and_accounts(self):
  service={'image':'ghcr.io/suwayomi/suwayomi-server@sha256:'+'a'*64,'environment':{'JAVA_TOOL_OPTIONS':'-Xms128m -Xmx768m -Dkeep=value','KCEF_ENABLED':'true'},'tmpfs':['/tmp:size=256m,mode=1777'],'volumes':['/data:/home/suwayomi/.local/share/Tachidesk'],'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'command':['/home/suwayomi/startup_script.sh']}
  original={'services':{'suwayomi':service,'importer':{'environment':{'SUWAYOMI_AUTH_FILE':'/private/auth'}}}};before=copy.deepcopy(original);updated=runtime.native_overlay(original);changed=updated['services']['suwayomi']
  self.assertEqual(original,before);self.assertEqual(updated['services']['importer'],original['services']['importer'])
  for key in ['image','cap_drop','security_opt','command']:self.assertEqual(changed[key],service[key])
  self.assertEqual(changed['volumes'][:-1],service['volumes'])
  mount=changed['volumes'][-1];self.assertEqual(mount['target'],runtime.JNI_TMP+'/Tachidesk');self.assertIn('/.codex-local/',mount['source']);self.assertFalse(mount['bind']['create_host_path'])
  self.assertIn('/tmp:size=256m,mode=1777',changed['tmpfs']);self.assertIn('exec,nosuid,nodev',changed['tmpfs'][-1]);self.assertIn('mode=0700',changed['tmpfs'][-1]);self.assertIn('-Dkeep=value',changed['environment']['JAVA_TOOL_OPTIONS']);self.assertIn('-Djava.io.tmpdir=/run/mediavault-jni',changed['environment']['JAVA_TOOL_OPTIONS'])
  self.assertEqual(runtime.native_overlay(updated),updated)
 def test_unpinned_or_public_service_cannot_be_modified(self):
  for s in [{'image':'example:latest'},{'image':'ghcr.io/suwayomi/suwayomi-server@sha256:'+'a'*64,'ports':['4567:4567']},{'image':'ghcr.io/suwayomi/suwayomi-server@sha256:'+'a'*64,'network_mode':'host'}]:
   with self.assertRaises(RuntimeError):runtime.native_overlay({'services':{'suwayomi':s}})
