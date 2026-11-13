"""VM pipelines behind the title page's save window for Google Drive:
ranobe/book audiobooks (and text + audio) and translated manga chapters.

Gemini voices, the narration director's browser, the manga renderer and Drive
are mocked here: these tests check contracts (what is sent, cached, encrypted,
resumed, paused). Real inference is recorded separately in
docs/drive-audiobook-and-manga-translation-2026-11-13.md.
"""
import asyncio
import base64
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import gemini_voice  # noqa: E402
import ranobe_audiobook  # noqa: E402
from ranobe_audiobook import PhraseCache, Paused, VoiceError, script_rows, speak, synthesize  # noqa: E402
from run_import import run_job, validate_job  # noqa: E402
from source_parser import SourceError  # noqa: E402
from vault_drive import VaultDrive, open_chunk  # noqa: E402
from test_vault_drive import FakeDrive, PHRASE  # noqa: E402
from test_server_import import FixtureHttp  # noqa: E402

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=')
PNG_RED = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC')


def decrypt(drive, vault, item):
    return b''.join(open_chunk(drive.download(c['fileId']), vault._key, item['id'], n, c['iv']) for n, c in enumerate(item['chunks']))


class DirectorScript(unittest.TestCase):
    def test_rows_keep_each_speaker_voice_and_style(self):
        rows = script_rows({'analysis': 'model', 'rows': [
            {'text': 'Он открыл дверь.', 'voice': 'Charon', 'style': 'авторский текст', 'pause': .3, 'kind': 'narration'},
            {'text': 'Кто здесь?', 'voice': 'Kore', 'style': 'прочитать реплику героя Аня (девушка)', 'pause': .22, 'kind': 'speech'},
            {'text': '   ', 'voice': 'Kore', 'style': '', 'pause': 0}]})
        self.assertEqual(rows, [{'text': 'Он открыл дверь.', 'voice': 'Charon', 'style': 'авторский текст', 'pause': .3},
                                {'text': 'Кто здесь?', 'voice': 'Kore', 'style': 'прочитать реплику героя Аня (девушка)', 'pause': .22}])

    def test_failed_role_pass_pauses_instead_of_voicing_bare_heuristics(self):
        with self.assertRaises(Paused):
            script_rows({'analysis': 'failed', 'rows': [{'text': 'А.', 'voice': 'Kore'}]})
        with self.assertRaises(SourceError):
            script_rows({'analysis': 'model', 'rows': [{'text': 'А.', 'voice': 'Somebody'}]})


class FakeLive:
    """Gemini Live stand-in: answers per key with audio, silence or a refusal."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, key, body):
        self.calls.append((key, body.text, body.voice, body.style))
        answer = self.answers.get(key, b'\x01\x00' * 9000)

        async def stream():
            if isinstance(answer, int):
                raise gemini_voice.LiveError(answer, 'refused')
            for at in range(0, len(answer), 4096):
                yield answer[at:at + 4096]
        return stream()


class Speaking(unittest.TestCase):
    def body(self, text='Привет.'):
        return gemini_voice.Speak(text=text, voice='Charon', style='ровно', language='ru')

    def test_quota_on_one_key_moves_the_phrase_to_the_next(self):
        live = FakeLive({'a': 429, 'b': b'\x02\x00' * 9000})
        data = asyncio.run(speak(['a', 'b'], self.body(), live=live, delay=0))
        self.assertEqual(data, b'\x02\x00' * 9000)
        self.assertEqual([c[0] for c in live.calls], ['a', 'b'])

    def test_every_key_out_of_quota_pauses_the_task(self):
        with self.assertRaises(Paused):
            asyncio.run(speak(['a', 'b'], self.body(), live=FakeLive({'a': 429, 'b': 429}), delay=0))

    def test_refused_keys_stop_with_a_clear_message(self):
        with self.assertRaises(VoiceError):
            asyncio.run(speak(['a'], self.body(), live=FakeLive({'a': 403}), delay=0))
        with self.assertRaises(VoiceError):
            asyncio.run(speak([], self.body(), live=FakeLive({}), delay=0))

    def test_silent_live_answer_is_read_by_the_speech_model(self):
        lines = []

        async def line(key, body):
            lines.append((key, body.text, body.voice))
            return b'\x03\x00' * 100
        data = asyncio.run(speak(['a', 'b'], self.body('Да.'), live=FakeLive({'a': b'\x00\x00' * 10}), line=line, delay=0))
        self.assertEqual(data, b'\x03\x00' * 100)
        self.assertEqual(lines, [('a', 'Да.', 'Charon')])

    def test_dropped_streams_are_retried_then_reported(self):
        with self.assertRaises(SourceError):
            asyncio.run(speak(['a'], self.body(), live=FakeLive({'a': 502}), delay=0))


class Synthesis(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        (self.folder / 'service.key').write_bytes(os.urandom(32))

    def test_chapter_pcm_keeps_order_voices_and_pauses_and_resumes_from_the_cache(self):
        rows = [{'text': 'Один.', 'voice': 'Charon', 'style': 'рассказчик', 'pause': .1},
                {'text': 'Два.', 'voice': 'Kore', 'style': 'реплика', 'pause': 0}]
        calls = []

        async def phrase(keys, body):
            calls.append((body.text, body.voice, body.style))
            await asyncio.sleep(.01 if body.text == 'Один.' else 0)
            return body.text.encode('utf-8')
        cache = PhraseCache(self.folder)
        pcm, identities = synthesize(rows, language='ru', keys=['k'], scope='lib', cache=cache, speak_phrase=phrase)
        self.assertEqual(sorted(calls), [('Два.', 'Kore', 'реплика'), ('Один.', 'Charon', 'рассказчик')])
        self.assertEqual(pcm, 'Один.'.encode() + bytes(int(.1 * 24000) * 2) + 'Два.'.encode())
        # The VM keeps voiced phrases sealed: no plaintext PCM on disk.
        stored = list((self.folder / '.codex-local' / 'audiobook-phrases').glob('*.pcm'))
        self.assertEqual(len(stored), 2)
        self.assertNotIn('Один.'.encode(), b''.join(p.read_bytes() for p in stored))
        calls.clear()
        again, _ = synthesize(rows, language='ru', keys=['k'], scope='lib', cache=cache, speak_phrase=phrase)
        self.assertEqual((again, calls), (pcm, []))
        cache.forget(identities)
        self.assertEqual(list((self.folder / '.codex-local' / 'audiobook-phrases').glob('*.pcm')), [])

    def test_a_quota_pause_keeps_phrases_voiced_so_far(self):
        rows = [{'text': str(i) + '.', 'voice': 'Kore', 'style': '', 'pause': 0} for i in range(6)]
        voiced = []

        async def phrase(keys, body):
            if body.text == '4.':
                await asyncio.sleep(.05)
                raise Paused(120)
            voiced.append(body.text)
            return b'\x00\x00'
        cache = PhraseCache(self.folder)
        with self.assertRaises(Paused):
            synthesize(rows, language='ru', keys=['k'], cache=cache, speak_phrase=phrase, parallel=2)
        kept = len(list((self.folder / '.codex-local' / 'audiobook-phrases').glob('*.pcm')))
        self.assertGreaterEqual(kept, 3)
        self.assertEqual(kept, len(voiced))

    def test_unknown_voice_is_refused(self):
        with self.assertRaises(VoiceError):
            synthesize([{'text': 'А.', 'voice': 'Nobody', 'style': '', 'pause': 0}], language='ru', keys=['k'])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is not installed')
    def test_pcm_becomes_a_tagged_ogg_opus_file(self):
        target = ranobe_audiobook.encode_opus(bytes(24000 * 2), self.folder / 'chapter.opus', tags={'title': 'Глава 1', 'album': 'Книга'})
        self.assertEqual(target.read_bytes()[:4], b'OggS')
        self.assertIn(b'OpusHead', target.read_bytes()[:200])
        probe = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(target), '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8')
        self.assertIn('Глава 1', probe.stderr)


class DriveAudiobook(unittest.TestCase):
    """run_job for ranobe with output text/audio/both, as the VM worker runs it."""
    URL = 'https://ranobehub.org/ranobe/1/1/3'
    DIRECTION = {'prefs': {'geminiNarrator': 'auto', 'narrator': 'auto', 'pace': 1, 'roles': True,
                           'rolesModel': 'gemini-3.5-flash-lite', 'bibleModel': 'gemini-3.5-flash-lite'},
                 'saved': {'Аня': {'voice': 'Leda', 'note': 'звонкий голос'}}, 'cast': {},
                 'bible': {'version': 2, 'characters': [{'name': 'Аня'}]}, 'language': 'ru'}

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        (self.folder / 'service.key').write_bytes(os.urandom(32))
        module = types.ModuleType('ranobe_sources')
        self.reads = []

        def chapter(url):
            self.reads.append(url)
            return {'title': 'Глава 3. Ночь', 'paragraphs': ['Первый абзац.', {'text': 'Второй абзац.'}]}
        module.chapter = chapter
        previous = sys.modules.get('ranobe_sources')
        sys.modules['ranobe_sources'] = module
        self.addCleanup(lambda: sys.modules.__setitem__('ranobe_sources', previous) if previous else sys.modules.pop('ranobe_sources', None))
        self.drive = FakeDrive()
        self.vault = VaultDrive(self.drive, sleep=lambda _: None)
        self.library = self.vault.initialize(PHRASE)
        self.spoken, self.scripts = [], []

    def job(self, output, direction=None):
        value = {'version': 3, 'library_id': self.library, 'sources': ['https://ranobehub.org/ranobe/1'], 'section': 'ranobe',
                 'collection': 'Ранобэ', 'quality': 'best', 'episodes': 'all', 'metadata': {'title': 'Ранобэ', 'authors': ['Автор']},
                 'dub': 'RanobeHub', 'translation': {}, 'output': output,
                 'entries': [{'number': 1, 'url': self.URL, 'title': 'Глава 3. Ночь', 'season': 1}]}
        if output != 'text':
            value['voice'] = direction or self.DIRECTION
        return value

    def audiobook(self, phrase=None):
        async def default(keys, body):
            self.spoken.append((tuple(keys), body.text, body.voice, body.style))
            return b'\x05\x00' * 2400

        def encode(pcm, target, tags):
            self.encoded = (pcm, tags)
            Path(target).write_bytes(b'OggS-fake-' + pcm[:16])
            return Path(target)

        def script(paragraphs, *, book_key, chapter_key, meta, direction, cancelled=None):
            self.scripts.append((paragraphs, book_key, chapter_key, meta['title'], meta['authors'], direction['saved']))
            return {'analysis': 'model', 'rows': [
                {'text': 'Первый абзац.', 'voice': 'Charon', 'style': 'авторский текст', 'pause': .3, 'kind': 'narration'},
                {'text': 'Второй абзац.', 'voice': 'Leda', 'style': 'прочитать реплику героя Аня', 'pause': .22, 'kind': 'speech'}]}
        return {'keys': lambda: ['k1', 'k2'], 'cache_dir': self.folder, 'speak': phrase or default, 'encode': encode, 'script': script}

    def run_import(self, job, **options):
        return run_job(job, self.vault, resolver=SimpleNamespace(http=None), log=lambda _: None, temporary_dir=self.folder, **options)

    def test_text_and_audio_are_two_encrypted_files_and_resume_skips_both(self):
        result = self.run_import(self.job('both'), audiobook=self.audiobook())
        self.assertEqual(result, {'saved': 1, 'skipped': 0, 'failed': 0})
        items = sorted(self.vault.refresh()['items'], key=lambda i: i['name'])
        self.assertEqual([(i['name'], i['mime'], i['category'], i['episode']) for i in items], [
            ('Ранобэ — глава 001.opus', 'audio/ogg', 'book', 1), ('Ранобэ — глава 001.txt', 'text/plain', 'book', 1)])
        self.assertEqual(decrypt(self.drive, self.vault, items[1]).decode(), 'Глава 3. Ночь\n\nПервый абзац.\n\nВторой абзац.')
        self.assertTrue(decrypt(self.drive, self.vault, items[0]).startswith(b'OggS-fake-'))
        # The VM director's multi-voice script is voiced row by row in its own voices.
        self.assertEqual(sorted((s[1], s[2]) for s in self.spoken), [('Второй абзац.', 'Leda'), ('Первый абзац.', 'Charon')])
        self.assertEqual(self.scripts, [(['Первый абзац.', 'Второй абзац.'], 'https://ranobehub.org/ranobe/1', self.URL, 'Ранобэ', ['Автор'],
                                         {'Аня': {'voice': 'Leda', 'note': 'звонкий голос'}})])
        self.assertEqual(self.encoded[1]['artist'], 'Автор')
        # Encrypted on Drive: the fake chunks never contain the plain text.
        self.assertNotIn('Первый абзац'.encode(), b''.join(self.drive.download(c['fileId']) for i in items for c in i['chunks']))
        # Voiced phrases are dropped from the VM cache once the chapter is in Drive.
        self.assertEqual(list((self.folder / '.codex-local' / 'audiobook-phrases').glob('*.pcm')), [])
        reads = len(self.reads)
        again = self.run_import(self.job('both'), audiobook=self.audiobook())
        self.assertEqual((again['skipped'], len(self.reads)), (1, reads))

    def test_audio_is_added_next_to_text_saved_earlier(self):
        self.assertEqual(self.run_import(self.job('text'))['saved'], 1)
        self.assertEqual(self.run_import(self.job('both'), audiobook=self.audiobook())['saved'], 1)
        names = sorted(i['name'] for i in self.vault.refresh()['items'])
        self.assertEqual(names, ['Ранобэ — глава 001.opus', 'Ранобэ — глава 001.txt'])
        # A grown bible is the same audiobook; another narrator is another one.
        grown = {**self.DIRECTION, 'bible': {'version': 2, 'characters': [{'name': 'Аня'}, {'name': 'Борис'}]}}
        self.assertEqual(self.run_import(self.job('audio', grown), audiobook=self.audiobook())['skipped'], 1)
        other = {**self.DIRECTION, 'prefs': {**self.DIRECTION['prefs'], 'geminiNarrator': 'Schedar'}}
        self.assertEqual(self.run_import(self.job('audio', other), audiobook=self.audiobook())['saved'], 1)
        self.assertEqual(len(self.vault.refresh()['items']), 3)

    def test_role_quota_pauses_too(self):
        audiobook = self.audiobook()
        audiobook['script'] = lambda *a, **k: {'analysis': 'failed', 'rows': []}
        with self.assertRaises(Paused):
            self.run_import(self.job('audio'), audiobook=audiobook)

    def test_quota_pause_leaves_the_task_to_the_worker_not_a_failure(self):
        async def exhausted(keys, body):
            raise Paused(120)
        with self.assertRaises(Paused):
            self.run_import(self.job('audio'), audiobook=self.audiobook(exhausted))
        self.assertEqual(self.vault.refresh()['items'], [])

    def test_a_failed_phrase_marks_the_chapter_failed_and_keeps_text(self):
        async def broken(keys, body):
            raise SourceError('Google не озвучил фразу главы.')
        result = self.run_import(self.job('both'), audiobook=self.audiobook(broken))
        self.assertEqual(result['failed'], 1)
        self.assertEqual([i['name'] for i in self.vault.refresh()['items']], ['Ранобэ — глава 001.txt'])

    def test_audio_without_the_import_server_voice_is_refused(self):
        with self.assertRaises(SourceError):
            self.run_import(self.job('audio'))

    def test_job_validation(self):
        self.assertEqual(validate_job(self.job('text'))['voice'], None)
        self.assertEqual(validate_job(self.job('both', {'language': 'uk'}))['voice']['prefs']['rolesModel'], 'gemini-3.5-flash-lite')
        prefs = self.DIRECTION['prefs']
        for bad in [{**self.DIRECTION, 'language': 'en'}, {**self.DIRECTION, 'key': 'secret'},
                    {**self.DIRECTION, 'prefs': {**prefs, 'rolesModel': 'gemini-3.5-flash'}},
                    {**self.DIRECTION, 'prefs': {**prefs, 'geminiNarrator': 'Nobody'}}, {**self.DIRECTION, 'prefs': {**prefs, 'pace': 9}},
                    {**self.DIRECTION, 'saved': 'Leda'}, {**self.DIRECTION, 'bible': {'x': 'y' * 170000}}]:
            with self.assertRaises(SourceError):
                validate_job(self.job('audio', bad))
        with self.assertRaises(SourceError):
            validate_job({**self.job('text'), 'output': 'video'})
        with self.assertRaises(SourceError):
            validate_job({**self.job('text'), 'section': 'anime', 'output': 'audio', 'entries': []})


class DriveMangaTranslation(unittest.TestCase):
    SOURCE = 'https://mangapoisk.me/manga/story/chapter/2-12.5'
    IMAGE = 'https://images.example/one.png'

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        (self.folder / 'service.key').write_bytes(os.urandom(32))
        self.drive = FakeDrive()
        self.vault = VaultDrive(self.drive, sleep=lambda _: None)
        self.library = self.vault.initialize(PHRASE)
        self.http = FixtureHttp({self.SOURCE: '<html lang="ru"><img class="page-image" src="' + self.IMAGE + '"></html>'}, {self.IMAGE: PNG})

    def job(self, render=None):
        value = {'version': 3, 'library_id': self.library, 'sources': [self.SOURCE], 'section': 'manga', 'collection': 'Манга', 'quality': 'best',
                 'episodes': 'all', 'metadata': {'title': 'Манга', 'kind': 'manga'}, 'dub': 'Команда',
                 'translation': {'name': 'Команда', 'kind': 'manga', 'language': 'ru'},
                 'entries': [{'number': 12.5, 'season': 2, 'url': self.SOURCE, 'title': 'Глава 12.5'}]}
        if render is not None:
            value.update(render=render, dub='Перевод MediaVault · Команда', translation={'name': 'Перевод MediaVault', 'kind': 'manga', 'language': 'ru'})
        return value

    def run_import(self, job, **options):
        return run_job(job, self.vault, resolver=SimpleNamespace(http=self.http), log=lambda _: None, temporary_dir=self.folder, **options)

    def test_vm_translates_then_encrypts_translated_pages(self):
        import functools
        from run_import import translate_chapter
        calls = []

        def translate(job, pages, options, skip, save, progress, budget):
            calls.append((job.owner, len(pages), options['language'], list(skip)))
            self.assertEqual(pages[0], PNG)
            budget.check()
            save(0, PNG_RED)
        translator = functools.partial(translate_chapter, 'owner-sub')
        with patch.dict(os.environ, {'DATA_DIR': str(self.folder)}), patch('manga_export_runtime.translate_pages', translate), \
                patch('manga_download.chapter_preview', return_value=None):
            self.assertEqual(self.run_import(self.job({'language': 'Japanese'}), manga_translator=translator)['saved'], 1)
            item = self.vault.refresh()['items'][0]
            self.assertEqual((item['dub'], item['episode'], item['season']), ('Перевод MediaVault · Команда', 12.5, 2))
            with zipfile.ZipFile(io.BytesIO(decrypt(self.drive, self.vault, item))) as archive:
                self.assertEqual([archive.read(n) for n in archive.namelist()], [PNG_RED])
            self.assertNotIn(PNG_RED, self.drive.download(item['chunks'][0]['fileId']))
            self.assertEqual(calls, [('owner-sub', 1, 'Japanese', [])])
            self.assertEqual(self.run_import(self.job({'language': 'Japanese'}), manga_translator=translator)['skipped'], 1)
            # The original chapter is a separate file with its own fingerprint.
            self.assertEqual(self.run_import(self.job())['saved'], 1)
            self.assertEqual(len(self.vault.refresh()['items']), 2)

    def test_translation_without_the_vm_translator_is_not_saved_as_original(self):
        result = self.run_import(self.job({'language': 'Japanese'}))
        self.assertEqual((result['saved'], result['failed']), (0, 1))
        self.assertEqual(self.vault.refresh()['items'], [])

    def test_render_validation(self):
        self.assertEqual(validate_job(self.job({'language': 'Korean', 'directModel': 'gemma-4-31b-it'}))['render']['directModel'], 'gemma-4-31b-it')
        for bad in [{'directModel': 'gemini-3.5-flash'}, {'language': 'Klingon'}, {'unknown': 1}]:
            with self.assertRaises(SourceError):
                validate_job(self.job(bad))
        with self.assertRaises(SourceError):
            validate_job({**self.job(), 'section': 'ranobe', 'render': {}})


class QueuePause(unittest.TestCase):
    def test_task_waiting_for_quota_is_not_picked_until_resume_time(self):
        from task_store import TaskStore
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with patch('os.chmod'), patch.object(Path, 'chmod'):
            store = TaskStore(folder)
        self.addCleanup(store.close)
        waiting = store.add('owner', {'job': {'section': 'ranobe'}}, 'idempotency-waiting-1')
        ready = store.add('owner', {'job': {'section': 'manga'}}, 'idempotency-ready-0001')
        store.update(waiting['id'], progress={'resumeAt': time.time() + 600})
        self.assertEqual(store.next()['id'], ready['id'])
        self.assertIsNone(store.next())
        store.update(waiting['id'], progress={'resumeAt': time.time() - 1})
        self.assertEqual(store.next()['id'], waiting['id'])


if __name__ == '__main__':
    unittest.main()
