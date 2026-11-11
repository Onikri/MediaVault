import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from player_catalog import voice_language,group_voices


class UkrainianVoiceTests(unittest.TestCase):
    def test_ukrainian_labels_are_recognised(self):
        for label in ['Украинский','Укр. Субтитры','Так Треба Продакшн','AMC (укр)','IНТЕР','Українське озвучення','FanVoxUA','Amanogawa']:
            self.assertEqual(voice_language(label),'uk',label)

    def test_russian_and_known_languages_are_not_changed(self):
        # Known Russian studios are labelled Russian (2a04b62); generic labels stay unknown.
        for label in ['AniLibria','LostFilm','Кубик в Кубе']:
            self.assertEqual(voice_language(label),'ru',label)
        for label in ['Дублированный','Гоблин']:
            self.assertEqual(voice_language(label),'und',label)
        self.assertEqual(voice_language('Украинский','en'),'en')
        self.assertEqual(voice_language('Сербин','ru'),'ru')

    def test_grouping_keeps_ukrainian_dub_separate(self):
        source={'url':'https://example.test/t','dubs':[
            {'id':'1','name':'Украинский','url':'https://example.test/1','language':'ru','episodes':[]},
            {'id':'2','name':'Дублированный','url':'https://example.test/2','language':'ru','episodes':[]}]}
        groups={g['name']:g['language'] for g in group_voices([source])}
        self.assertEqual(groups,{'Украинский':'uk','Дублированный':'ru'})


if __name__=='__main__':unittest.main()
