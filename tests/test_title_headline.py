import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from title_identity import match_title,headline

LONG_RU='Изгнанный читер-чародей наслаждается беззаботной второй жизнью: Я могу накладывать «очки усиления» не только на оружие, но и на что угодно'
LONG_ROMAJI='Tsuihou sareta Cheat Fuyo Majutsushi wa Kimama na Second Life wo Ouka suru. Ore wa Buki dake ja Naku, Arayuru Mono ni "Kyouka Point" wo Fuyo Dekiru shi'
SELECTED={'title':LONG_RU,'titles':{'ru':LONG_RU,'en':LONG_ROMAJI},'year':2026,'kind':'anime'}


class Headline(unittest.TestCase):
    def test_site_listing_without_the_light_novel_subtitle_matches(self):
        self.assertEqual(match_title(SELECTED,{'title':'Изгнанный читер-чародей наслаждается беззаботной второй жизнью','kind':'anime'}),(True,'headline'))
        self.assertEqual(match_title(SELECTED,{'title':'Tsuihou sareta Cheat Fuyo Majutsushi wa Kimama na Second Life wo Ouka suru','kind':'anime'}),(True,'headline'))

    def test_year_and_external_id_still_decide(self):
        self.assertEqual(match_title(SELECTED,{'title':'Изгнанный читер-чародей наслаждается беззаботной второй жизнью','year':2019,'kind':'anime'})[1],'different_year')
        self.assertEqual(match_title({**SELECTED,'ids':{'mal':'63431'}},{'title':'Изгнанный читер-чародей наслаждается беззаботной второй жизнью','ids':{'mal':'1'},'kind':'anime'})[1],'different_id')

    def test_short_season_subtitles_stay_distinct(self):
        self.assertFalse(match_title({'title':'Атака титанов: Финал','kind':'anime'},{'title':'Атака титанов','kind':'anime'})[0])
        self.assertFalse(match_title({'title':'Моя геройская академия: Два героя','kind':'anime'},{'title':'Моя геройская академия','kind':'anime'})[0])
        self.assertFalse(match_title({'title':'Re:Zero. Жизнь с нуля в альтернативном мире','kind':'anime'},{'title':'Re','kind':'anime'})[0])
        self.assertEqual(headline('Атака титанов: Финал'),'')
        self.assertEqual(headline('Без подзаголовка вообще тут нет'),'')


if __name__=='__main__':unittest.main()
