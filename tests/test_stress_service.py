"""Word stress transfer for narration (offline: RUAccent outputs recorded 2026-11-08).

The real model runs on the server; these tests pin how its '+' marks become
U+0301 on the ORIGINAL text without changing any letter, punctuation or space.
"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stress_service as ss

A = '́'
RECORDED = {
    '— Замок на двери старого замка уже заржавел… — сказала она.':
        '— З+амок на двер+и ст+арого замк+а уж+е заржав+ел — сказ+ала он+а.',
    'Ещё мгновение — и всё изменится, подумал Кайто.':
        'Ещ+ё мгнов+ение — и всё изм+енится, под+умал Кайто.',
    'Он сказал: «Ёлки-палки, кто-то идёт!»':
        '+Он сказ+ал: «Ёлки-п+алки, кт+о-то идёт!»',
    'Ночь опустилась на город, и только в окне старой библиотеки еще горел свет.':
        'Н+очь опуст+илась на г+ород, и т+олько в окн+е ст+арой библиот+еки ещё гор+ел свет.',
}


class Transfer(unittest.TestCase):
    def test_marks_land_on_the_original_letters(self):
        for original, accented in RECORDED.items():
            value = ss.transfer(original, accented)
            self.assertEqual(ss.plain(value), ss.plain(original), value)
        self.assertEqual(ss.transfer(*list(RECORDED.items())[0]),
                         '— За' + A + 'мок на двери' + A + ' ста' + A + 'рого замка' + A + ' уже' + A + ' заржаве' + A + 'л… — сказа' + A + 'ла она' + A + '.')

    def test_one_syllable_words_stay_plain_and_yo_is_restored(self):
        value = ss.transfer(*list(RECORDED.items())[3])
        self.assertTrue(value.startswith('Ночь опусти' + A + 'лась'))
        self.assertIn('ещё горе' + A + 'л свет', value)
        self.assertEqual(ss.transfer(*list(RECORDED.items())[2]), 'Он сказа' + A + 'л: «Ёлки-па' + A + 'лки, кто' + A + '-то идёт!»')

    def test_unknown_words_and_dropped_tokens_keep_the_original(self):
        self.assertIn('Кайто.', ss.transfer(*list(RECORDED.items())[1]))
        self.assertEqual(ss.transfer('Привет, мир!', 'Пр+ив+ет'), 'Привет, мир!')  # ambiguous double mark → one index only
        self.assertEqual(ss.plain(ss.transfer('abc — тест', 'abc — т+ест')), ss.plain('abc — тест'))

    def test_requests_are_validated_and_ukrainian_is_passed_through(self):
        self.assertEqual(ss.stress(['Привіт'], 'uk'), ['Привіт'])
        with self.assertRaises(ValueError):
            ss.stress([], 'ru')
        with self.assertRaises(ValueError):
            ss.stress(['я' * 5000], 'ru')

    def test_loading_answers_warming_until_ready(self):
        started = []
        original_start, original_engine = ss.start, ss._engine
        ss.start = lambda: started.append(True)
        ss._engine = None
        try:
            with self.assertRaises(ss.Warming):
                ss.stress(['Привет'], 'ru')
            self.assertEqual(started, [True])
        finally:
            ss.start, ss._engine = original_start, original_engine


@unittest.skipUnless(__import__('importlib').util.find_spec('ruaccent') and (Path(ss.os.getenv('DATA_DIR', '/data')) / 'models' / 'ruaccent' / 'nn').is_dir(),
                     'RUAccent and its models are not installed here')
class RealModel(unittest.TestCase):
    """Actual RUAccent inference (runs where the model is present)."""

    def test_real_model(self):
        import time
        ss.start()
        for _ in range(600):
            if ss.status()['phase'] != 'loading': break
            time.sleep(.5)
        out = ss.stress(['Пьер Безухов и Андрей Болконский встретили Наташу Ростову.'], 'ru')[0]
        self.assertIn('Безу' + A + 'хов', out)
        self.assertIn('Ната' + A + 'шу', out)


if __name__ == '__main__':
    unittest.main()
