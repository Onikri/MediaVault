"""Real local-LLM probes. Anchors flag omissions; they are not a quality score."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from lmt_translate import SegmentTranslator

PROBES = [
    ('Japanese', 'retirement', '今日が引退前の最後の日になると思う', ['пенси', 'последн']),
    ('Japanese', 'home-and-grandchild', 'ああ家に帰って成長した孫の姿を見るのが楽しみだ', ['дом', 'вну', 'вырос|подрос|взросл']),
    ('Japanese', 'negation', 'もう帰らないとは言っていない。', ['не', 'говор|сказ', 'верн|возвращ']),
    ('Korean', 'station-directions', '고엔지 역에 가려면 어느 쪽으로 가야 하나요?', ['коэн|коен|коэндз', 'станц|вокзал', 'как|куда|сторон|направлен']),
    ('Chinese', 'free-tasting-not-price', '这是免费的试吃，不是新菜单的正式价格。', ['бесплат', 'проб|дегустац', 'не', 'цен']),
    ('English', 'uncertainty-not-accusation', "I didn't say he stole the key; I said he might have borrowed it.", ['не', 'укра', 'ключ', 'возмож|может', 'одолж|взял']),
]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = []
    translator = SegmentTranslator()
    for language, concept, source, anchors in PROBES:
        start = time.perf_counter()
        result = await translator.translate({'texts':[source], 'source':language, 'target':'Russian'})
        text = result['translations'][0]
        missing = [anchor for anchor in anchors if not re.search(anchor, text.lower())]
        record = {'language':language, 'concept':concept, 'source':source, 'translation':text,
                  'seconds':round(time.perf_counter()-start, 3), 'missingAnchors':missing}
        results.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    report = {'model':os.environ['LMT_LLM_MODEL'], 'profile':'segments', 'realInference':True,
              'note':'Lexical anchors detect specific regressions only. Review meaning manually.', 'probes':results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
