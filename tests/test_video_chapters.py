"""Video chapters contract: subtitle parsing and checks, windowing, model answers, formats and the record cache.

Every model and network call here is a fake: this file tests the contract, not real inference.
Real model measurements live in .codex-local/chapters-bench (not committed).
"""
import asyncio, gzip, json, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import video_chapters as vc


def vtt(n=60, step=20, offset=0):
    rows = ['WEBVTT', '']
    for i in range(n):
        s = offset + i * step
        rows += [f'{vc.vtt_time(s)} --> {vc.vtt_time(s + 3)}', f'Реплика номер {i} про героя и его дела', '']
    return '\n'.join(rows)


def answer(rows):
    return {'candidates': [{'content': {'parts': [{'text': json.dumps({'chapters': [{'start': vc.clock(s), 'end': vc.clock(s), 'title': t} for s, t in rows]}, ensure_ascii=False)}]},
                            'finishReason': 'STOP'}], 'usageMetadata': {'promptTokenCount': 100}}


def text_of(request):
    return request['contents'][-1]['parts'][0]['text']


class Parsing(unittest.TestCase):
    def test_vtt_srt_and_ass_become_clean_cues_without_ads(self):
        srt = '1\n00:00:06,000 --> 00:00:12,074\nНажмите воспроизведение.\n200+ языков: tryray.app\n\n2\n00:01:15,000 --> 00:01:18,840\n<i><font color="#ffff00">Двенадцатью часами ранее</font></i>\n'
        cues = vc.parse_subtitles(srt)
        self.assertEqual([(75.0, 78.84, 'Двенадцатью часами ранее')], cues)
        ass = ('[Script Info]\nTitle: x\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
               'Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,{\\an8}Привет,\\Nмир\n')
        self.assertEqual([(1.5, 3.0, 'Привет, мир')], vc.parse_subtitles(ass))
        self.assertEqual(60, len(vc.parse_subtitles(vtt())))

    def test_checks_reject_forced_tracks_and_other_releases(self):
        cues = vc.parse_subtitles(vtt(60, 20))
        self.assertIsNone(vc.check_subtitles(cues, 1300))
        self.assertIn('мало', vc.check_subtitles(cues[:10], 1300))
        self.assertIn('длиннее', vc.check_subtitles(cues, 600))
        self.assertIn('меньше половины', vc.check_subtitles(cues, 4000))

    def test_long_videos_are_cut_into_windows_at_pauses(self):
        self.assertEqual([(0, 1500)], vc.windows(vc.parse_subtitles(vtt(70, 20)), 1500))
        cues = vc.parse_subtitles(vtt(300, 20))
        cues = [c for c in cues if not 1450 <= c[0] < 1480]  # a 30-second pause near the 25-minute mark
        parts = vc.windows(cues, 6000)
        self.assertEqual(0, parts[0][0])
        self.assertEqual(6000, parts[-1][1])
        self.assertEqual(1480, parts[0][1])
        self.assertTrue(all(a < b for a, b in parts))


    def test_chapters_stay_navigation_sized(self):
        thirty = [[i * 119, f'Сцена {i}'] for i in range(30)]
        kept = vc.normalize(thirty, 3572)
        self.assertLessEqual(len(kept), 18)
        self.assertTrue(all(b[0] - a[0] >= 79 for a, b in zip(kept, kept[1:])))
        self.assertEqual(13, vc.scene_target(3572))
        self.assertIn('около 6 глав', vc.user_text({'title': 'X'}, [], 0, 1500, 1500, True))


class Model(unittest.TestCase):
    def test_answer_times_are_strings_inside_the_window(self):
        self.assertEqual([[0, 'Пролог'], [83, 'Долги Дэндзи']], vc.read_answer(json.dumps({'chapters': [
            {'start': '0:00', 'end': '1:23', 'title': '«Пролог».'}, {'start': '1:23', 'end': '5:00', 'title': 'Долги Дэндзи'}]}), 0, 300))
        with self.assertRaises(ValueError):
            vc.read_answer(json.dumps({'chapters': [{'start': 340, 'end': '', 'title': 'x'}]}), 0, 300)
        with self.assertRaises(ValueError):
            vc.read_answer(json.dumps({'chapters': [{'start': '9:00', 'end': '', 'title': 'x'}]}), 0, 300)

    def test_one_request_for_an_episode_and_a_repair_turn_for_a_bad_answer(self):
        calls = []

        async def call(model, request):
            calls.append((model, request))
            if len(calls) == 1:
                return answer([(0, 'Пролог'), (9999, 'Вне серии')])
            return answer([(0, 'Пролог'), (300, 'Охота на демона'), (310, 'Слишком близко')])
        cues = vc.parse_subtitles(vtt(70, 20))
        chapters, stats = asyncio.run(vc.generate(call, {'title': 'Тест'}, cues, 1500))
        self.assertEqual([[0, 'Пролог'], [300, 'Охота на демона']], chapters)
        self.assertEqual(2, stats['requests'])
        self.assertEqual({'gemini-3.1-flash-lite'}, {m for m, _ in calls})
        self.assertEqual('model', calls[1][1]['contents'][1]['role'])
        self.assertIn('не подошёл', text_of(calls[1][1]))
        body = calls[0][1]
        self.assertEqual('low', body['generationConfig']['thinkingConfig']['thinkingLevel'])
        self.assertIn('responseJsonSchema', body['generationConfig'])
        self.assertIn('от 2 до 6 слов', body['systemInstruction']['parts'][0]['text'])
        self.assertNotIn('фрагмент', text_of(body))

    def test_a_film_goes_as_parallel_windows_and_a_refused_window_is_split(self):
        seen = []

        async def call(model, request):
            text = text_of(request)
            seen.append(text)
            span = text.split('Это фрагмент видео с ')[1].split('.')[0].split(' до ')
            lo, hi = vc.model_seconds(span[0]), vc.model_seconds(span[1])
            if lo == 0 and hi > 1200:
                return {'promptFeedback': {'blockReason': 'PROHIBITED_CONTENT'}}
            return answer([(lo, 'Сцена ' + vc.clock(lo)), (lo + 200, 'Дальше ' + vc.clock(lo))])
        cues = vc.parse_subtitles(vtt(300, 20))
        chapters, stats = asyncio.run(vc.generate(call, {'title': 'Фильм'}, cues, 6000))
        self.assertGreater(stats['windows'], 3)
        self.assertEqual(0, chapters[0][0])
        self.assertTrue(all(b[0] - a[0] >= vc.MIN_GAP for a, b in zip(chapters, chapters[1:])))
        self.assertTrue(any('видео с 0:00 до 12:' in t for t in seen), 'the refused first window is asked again in halves')

    def test_quota_on_every_key_falls_back_to_the_other_lite_model(self):
        class Limited(Exception):
            status = 429

        async def call(model, request):
            if model == vc.PRIMARY:
                raise Limited()
            return answer([(0, 'Начало охоты'), (400, 'Бой с демоном')])
        chapters, _ = asyncio.run(vc.generate(call, {}, vc.parse_subtitles(vtt(70, 20)), 1500))
        self.assertEqual(2, len(chapters))


class Formats(unittest.TestCase):
    record = {'d': 1500, 'c': [[0, 'Долги & демоны'], [83, 'Контракт с Почитой'], [900, 'Бой']]}

    def test_webvtt_chapters(self):
        text = vc.to_webvtt(self.record)
        self.assertTrue(text.startswith('WEBVTT'))
        self.assertIn('00:01:23.000 --> 00:15:00.000\nКонтракт с Почитой', text)
        self.assertIn('00:15:00.000 --> 00:25:00.000', text)
        self.assertIn('00:15:00.000 --> 00:24:00.000', vc.to_webvtt(self.record, 1440))

    def test_matroska_xml_is_valid_with_stable_unique_ids(self):
        text = vc.to_matroska(self.record, 'a' * 32)
        root = ET.fromstring(text.split('\n', 2)[2])
        atoms = root.findall('./EditionEntry/ChapterAtom')
        self.assertEqual(3, len(atoms))
        self.assertEqual('00:01:23.000000000', atoms[1].findtext('ChapterTimeStart'))
        self.assertEqual('Долги & демоны', atoms[0].findtext('ChapterDisplay/ChapterString'))
        self.assertEqual('rus', atoms[0].findtext('ChapterDisplay/ChapterLanguage'))
        ids = [a.findtext('ChapterUID') for a in atoms]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(text, vc.to_matroska(self.record, 'a' * 32))

    def test_ffmetadata_escapes(self):
        text = vc.to_ffmetadata({'d': 100, 'c': [[0, 'a=b;c']]})
        self.assertIn('title=a\\=b\\;c', text)
        self.assertIn('END=100000', text)


class Sources(unittest.TestCase):
    def test_collaps_full_russian_track_first_for_the_episode(self):
        page = 'var x = {seasons: [{"season": 1, "episodes": [{"episode": "1", "cc": [' \
               '{"url": "https://cdn.example/a.vtt", "name": "Рус. форсированные"}, {"url": "https://cdn.example/b.vtt", "name": "Eng. full"},' \
               '{"url": "https://cdn.example/c.vtt", "name": "Рус. полные"}]}, {"episode": "2", "cc": [{"url": "https://cdn.example/d.vtt", "name": "Рус. полные"}]}]}]}'
        self.assertEqual(['c', 'b', 'a'], [t['url'][-5] for t in vc.collaps_tracks(page, 1, 1)])
        self.assertEqual(['e'], [t['url'][-5] for t in vc.collaps_tracks('cc: [{"url":"https://x/e.vtt","name":"Eng"}]')])

    def test_opensubtitles_pick_matches_episode_title_and_prefers_russian(self):
        rows = [{'SubFormat': 'srt', 'SeriesSeason': '1', 'SeriesEpisode': '2', 'MovieName': '"Breaking Bad" Cat\'s in the Bag', 'SubLanguageID': 'eng', 'SubDownloadsCnt': '9'},
                {'SubFormat': 'srt', 'SeriesSeason': '1', 'SeriesEpisode': '2', 'MovieName': '"Breaking Bad" Cat\'s in the Bag', 'SubLanguageID': 'rus', 'SubDownloadsCnt': '1'},
                {'SubFormat': 'srt', 'SeriesSeason': '1', 'SeriesEpisode': '3', 'MovieName': '"Breaking Bad" x', 'SubLanguageID': 'rus'},
                {'SubFormat': 'srt', 'SeriesSeason': '1', 'SeriesEpisode': '2', 'MovieName': '"Other Show" x', 'SubLanguageID': 'rus'},
                {'SubFormat': 'sub', 'SeriesSeason': '1', 'SeriesEpisode': '2', 'MovieName': '"Breaking Bad" x', 'SubLanguageID': 'rus'}]
        picked = vc.opensubtitles_pick(rows, {'names': ['Breaking Bad'], 'season': 1, 'episode': 2})
        self.assertEqual(['rus', 'eng'], [r['SubLanguageID'] for r in picked])
        self.assertEqual(['episode-2/query-breaking%20bad/season-1'], vc.opensubtitles_queries({'names': ['Во все тяжкие', 'Breaking Bad'], 'season': 1, 'episode': 2}))
        self.assertEqual('imdbid-0903747', vc.opensubtitles_queries({'imdb': 'tt0903747', 'names': []})[0])

    def test_opensubtitles_download_is_gunzipped_and_decoded(self):
        payload = gzip.compress('1\n00:00:01,000 --> 00:00:02,000\nПривет\n'.encode('cp1251'))

        class Response:
            def __init__(self, status, data=None, content=b''):
                self.status_code, self._data, self.content = status, data, content

            def json(self):
                return self._data

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                if 'rest.opensubtitles.org' in url:
                    return Response(200, [{'SubFormat': 'srt', 'MovieName': 'Reze Arc', 'MovieKind': 'movie', 'SubLanguageID': 'rus', 'SubEncoding': 'CP1251',
                                           'SubDownloadLink': 'https://dl.opensubtitles.org/x.gz', 'LanguageName': 'Russian'}])
                return Response(200, content=payload)

        async def collect():
            return [v async for v in vc.Sources(client_factory=Client).opensubtitles({'names': ['Reze Arc']})]
        found = asyncio.run(collect())
        self.assertEqual('opensubtitles', found[0][1])
        self.assertIn('Привет', found[0][0])


class Service(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_service(self, sources, meta, call=None, rounds=1):
        calls = []

        async def default_call(model, request):
            calls.append(model)
            return answer([(0, 'Долги Дэндзи'), (300, 'Охота на демона')])

        async def scenario():
            service = vc.VideoChapters(self.temp.name, call or default_call, sources=sources)
            states = []
            for _ in range(rounds):
                states.append(service.prepare(dict(meta)))
                while service.jobs:
                    await asyncio.sleep(0.01)
                states.append(service.state(states[-1]['key']))
            return states
        return asyncio.run(scenario()), calls

    class Fake:
        def __init__(self, collaps=(), library=()):
            self.collaps_rows, self.library_rows, self.asked = list(collaps), list(library), []

        async def collaps(self, urls, meta):
            self.asked.append('collaps')
            for row in self.collaps_rows:
                yield row

        async def opensubtitles(self, meta):
            self.asked.append('opensubtitles')
            for row in self.library_rows:
                yield row

    def test_ready_record_is_tiny_and_served_from_cache(self):
        fake = self.Fake(collaps=[('WEBVTT\n\n00:00.000 --> 00:01.000\nx\n', 'collaps', 'Collaps · форсированные'), (vtt(70, 20), 'collaps', 'Collaps · Рус. полные')])
        meta = {'work': '44511', 'season': 1, 'episode': 1, 'title': 'Человек-бензопила', 'collaps': ['https://api.nextembed.ws/embed/kp/1'], 'duration': 1440}
        (first, done, again, cached), calls = self.run_service(fake, meta, rounds=2)
        self.assertEqual('working', first['state'])
        self.assertEqual('ready', done['state'])
        self.assertEqual([{'start': 0, 'title': 'Долги Дэндзи'}, {'start': 300, 'title': 'Охота на демона'}], done['chapters'])
        self.assertEqual('Collaps · Рус. полные', done['source'])
        self.assertEqual('ready', again['state'])
        self.assertEqual(1, len(calls))
        self.assertEqual(['collaps'], fake.asked)
        path = vc.Store(self.temp.name).path(done['key'])
        self.assertLess(path.stat().st_size, 400)

    def test_redo_keeps_showing_the_markup_it_replaces(self):
        record = {'v': vc.VERSION, 'd': 1500, 'c': [[0, 'Старое'], [600, 'Погоня']], 's': 'Collaps', 'q': 2}
        state = vc.public('k', record, {'step': 'Размечаем сцены'})
        self.assertEqual('working', state['state'])
        self.assertEqual([{'start': 0, 'title': 'Старое'}, {'start': 600, 'title': 'Погоня'}], state['chapters'])
        self.assertNotIn('chapters', vc.public('k', None, {'step': 'В очереди'}))

    def test_a_dense_version_one_record_is_thinned_once_without_the_model(self):
        store = vc.Store(self.temp.name)
        key = vc.record_key('bird', 1, 2)
        store.write(key, {'v': 1, 'd': 3572, 'c': [[i * 119, f'Сцена {i}'] for i in range(30)], 's': 'Alloha', 'q': 3})
        record = store.read(key)
        self.assertEqual(vc.VERSION, record['v'])
        self.assertLessEqual(len(record['c']), 18)
        self.assertEqual(0, record['c'][0][0])
        self.assertEqual(record, json.loads(store.path(key).read_text('utf-8')))

    def test_player_subtitles_upgrade_a_library_record_once(self):
        store = vc.Store(self.temp.name)
        key = vc.record_key('7', 0, 0)
        store.write(key, {'v': 1, 'd': 1500, 'c': [[0, 'Старое']], 's': 'OpenSubtitles · English', 'q': 1})
        meta = {'work': '7', 'subtitle': {'text': vtt(70, 20), 'origin': 'player', 'label': 'Alloha · Русские'}}
        (first, done), calls = self.run_service(self.Fake(), meta)
        self.assertEqual('working', first['state'])
        self.assertEqual('Alloha · Русские', done['source'])
        (again, _), more = self.run_service(self.Fake(), meta)
        self.assertEqual('ready', again['state'])
        self.assertEqual([], more)

    def test_nothing_found_is_remembered_for_a_while(self):
        fake = self.Fake()
        (first, done), _ = self.run_service(fake, {'work': '9', 'names': ['Nothing']})
        self.assertEqual('none', done['state'])
        (again, _), _ = self.run_service(fake, {'work': '9', 'names': ['Nothing']})
        self.assertEqual('none', again['state'])
        self.assertEqual(['opensubtitles'], fake.asked)


if __name__ == '__main__':
    unittest.main()
