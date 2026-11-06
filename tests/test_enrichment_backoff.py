"""Background enrichment must not repeat network and Drive work on every visit."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import library_enrichment as enrichment
from vault_drive import VaultDrive
from test_vault_drive import FakeDrive,PHRASE

HOUR=enrichment.HOUR_MS
NOW=1_800_000_000_000

def partial_profile(identity,kind):
    return {'version':4,'source':'shikimori','sourceId':str(identity),'title':'Тайтл','description':'','partial':True,'retryAfter':0,
            'screenshots':[],'characters':[],'related':[],'staff':[],'trailers':[]}

def complete_profile(identity,kind):
    return {**partial_profile(identity,kind),'description':'Описание','genres':['Драма'],'partial':False}

class EnrichmentBackoff(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.drive=FakeDrive();self.vault=VaultDrive(self.drive);self.vault.initialize(PHRASE);self.addCleanup(self.vault.close)

    def add(self,category,section,count,metadata_id=101):
        for episode in range(1,count+1):
            path=Path(self.folder.name)/f'{section}-{episode}.bin';path.write_bytes(b'x'*64)
            self.vault.upload_file(path,category=category,section=section,collection='Тайтл '+section,episode=episode,
                                   metadata_id=metadata_id,metadata={'ids':{'mal':str(metadata_id)}},mime='application/zip' if category=='manga' else 'video/mp4')
        self.vault.refresh()

    def run_all(self,now):
        cursor,steps,saved=0,0,0
        while True:
            result=enrichment.enrichment_step(self.vault,cursor=cursor,now=now)
            steps+=1;saved+=result['saved'];cursor=result['cursor']
            if not result['remaining']:return steps,saved

    def test_partial_dossier_backs_off_and_eventually_stops(self):
        self.add('manga','manga',6)
        loads=mock.Mock(side_effect=partial_profile)
        with mock.patch.object(enrichment,'load_profile',loads):
            steps,saved=self.run_all(NOW)
            # One dossier request for six chapters, not one per chapter.
            self.assertEqual(loads.call_count,1);self.assertEqual(saved,1)
            profile=next(iter(self.vault.catalog['titleProfiles'].values()))
            self.assertEqual(profile['profileAttempts'],1);self.assertEqual(profile['retryAfter'],NOW+6*HOUR)
            writes=len(self.drive.patches)
            # Reopening the library a minute later costs neither requests nor writes.
            self.assertEqual(self.run_all(NOW+60_000)[1],0)
            self.assertEqual(loads.call_count,1);self.assertEqual(len(self.drive.patches),writes)
            now=NOW
            for _ in range(enrichment.PROFILE_RETRY_LIMIT-1):
                now=next(iter(self.vault.catalog['titleProfiles'].values()))['retryAfter']
                self.run_all(now)
            self.assertEqual(loads.call_count,enrichment.PROFILE_RETRY_LIMIT)
            self.run_all(now+365*24*HOUR)
            self.assertEqual(loads.call_count,enrichment.PROFILE_RETRY_LIMIT)

    def test_complete_dossier_is_not_refetched_or_rewritten(self):
        self.add('manga','manga',3)
        loads=mock.Mock(side_effect=complete_profile)
        with mock.patch.object(enrichment,'load_profile',loads):
            self.run_all(NOW);writes=len(self.drive.patches)
            profile=next(iter(self.vault.catalog['titleProfiles'].values()))
            self.assertEqual(profile['profileAttempts'],0);self.assertFalse(enrichment.profile_due(profile,NOW+10**12))
            self.assertEqual(self.run_all(NOW+30*24*HOUR)[1],0)
            self.assertEqual(loads.call_count,1);self.assertEqual(len(self.drive.patches),writes)

    def test_failed_episode_frame_is_remembered(self):
        self.add('video','anime',2)
        frames=mock.Mock(return_value=None)
        with mock.patch.object(enrichment,'preview_existing',frames),mock.patch.object(enrichment,'load_profile',complete_profile):
            self.run_all(NOW)
            self.assertEqual(frames.call_count,2)
            self.assertTrue(all(item['previewAttempts']==1 and item['previewRetryAfter']==NOW+6*HOUR for item in self.vault.catalog['items']))
            self.run_all(NOW+HOUR);self.assertEqual(frames.call_count,2)
            for attempt in range(2,enrichment.PREVIEW_RETRY_LIMIT+1):
                self.run_all(self.vault.catalog['items'][0]['previewRetryAfter'])
                self.assertEqual(frames.call_count,2*attempt)
            self.run_all(NOW+365*24*HOUR);self.assertEqual(frames.call_count,2*enrichment.PREVIEW_RETRY_LIMIT)

    def test_idle_library_finishes_in_one_step_without_writes(self):
        self.add('manga','manga',40)
        with mock.patch.object(enrichment,'load_profile',complete_profile):self.run_all(NOW)
        writes=len(self.drive.patches)
        steps,saved=self.run_all(NOW+HOUR)
        self.assertEqual((steps,saved),(1,0));self.assertEqual(len(self.drive.patches),writes)

if __name__=='__main__':unittest.main()
