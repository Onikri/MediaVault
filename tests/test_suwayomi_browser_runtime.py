import importlib.util,unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('browser_runtime',Path(__file__).resolve().parents[1]/'deploy/oracle/enable-suwayomi-browser.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


class BrowserRuntimeTests(unittest.TestCase):
    def test_repair_preserves_pinned_image_network_data_and_auth_settings(self):
        original={'services':{'suwayomi':{'image':'ghcr.io/suwayomi/suwayomi-server@sha256:'+'a'*64,'entrypoint':['java','-Djava.awt.headless=true'],'volumes':['/private/source-data:/data'],'environment':{'TZ':'Etc/UTC'},'cap_drop':['ALL'],'security_opt':['no-new-privileges:true']},'importer':{'environment':{'SUWAYOMI_AUTH_FILE':'/private/auth'}}}}
        updated=runtime.browser_overlay(original)
        for key in ['image','volumes','cap_drop','security_opt']:self.assertEqual(updated['services']['suwayomi'][key],original['services']['suwayomi'][key])
        self.assertEqual(updated['services']['importer'],original['services']['importer'])
        self.assertNotIn('KCEF_ENABLED',original['services']['suwayomi']['environment'])
        self.assertEqual(updated['services']['suwayomi']['environment']['KCEF_ENABLED'],'true')
        self.assertNotIn('headless=true',' '.join(updated['services']['suwayomi']['entrypoint']))

    def test_repair_refuses_unpinned_or_public_services(self):
        for source in [{'image':'untrusted:latest'},{'image':'ghcr.io/suwayomi/suwayomi-server@sha256:'+'a'*64,'ports':['4567:4567']},{'image':'ghcr.io/suwayomi/suwayomi-server@sha256:'+'a'*64,'network_mode':'host'}]:
            with self.assertRaises(RuntimeError):runtime.browser_overlay({'services':{'suwayomi':source}})
