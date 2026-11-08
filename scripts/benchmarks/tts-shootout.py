"""Russian/Ukrainian TTS shoot-out: real ONNX inference, then Whisper round-trip CER.

Usage (inside an isolated venv with onnxruntime, numpy, soundfile, faster-whisper,
jiwer, piper-tts):

    python -I scripts/benchmarks/tts-shootout.py --models <dir> --out <dir>

<models> holds Supertonic 3 variants as <variant>/onnx/*.onnx + voice_styles/*.json
and Piper voices as piper/<voice>.onnx(+.json). Nothing here is mocked: every
number comes from actually synthesised audio. CER measures intelligibility only;
it says nothing about naturalness, so the WAVs are kept for listening.
"""
import argparse, json, os, re, time, unicodedata, wave
from pathlib import Path
import numpy as np

SENTENCES = {
    'ru': [
        'Ночь опустилась на город, и только в окне старой библиотеки ещё горел свет.',
        '— Ты опять опоздал, — недовольно сказала Мирэй, скрестив руки на груди.',
        '— Прости, я заблудился в северном квартале, — виновато ответил Кайто.',
        'Ветер принёс запах дождя, а где-то вдали глухо прогремел гром.',
        '— Неужели ты и правда думаешь, что мы победим? — прошептала она.',
        '— Конечно! Мы зашли слишком далеко, чтобы теперь отступать!',
        'Старик медленно поднялся, опираясь на посох, и посмотрел на юношу.',
        '— Магия требует платы, мальчик. Всегда.',
    ],
    'uk': [
        'Ніч опустилася на місто, і лише у вікні старої бібліотеки ще горіло світло.',
        '— Ти знову запізнився, — невдоволено сказала Мірей, схрестивши руки на грудях.',
        '— Пробач, я заблукав у північному кварталі, — винувато відповів Кайто.',
        'Вітер приніс запах дощу, а десь удалині глухо прогримів грім.',
        '— Невже ти справді думаєш, що ми переможемо? — прошепотіла вона.',
        '— Звісно! Ми зайшли надто далеко, щоб тепер відступати!',
        'Старий повільно підвівся, спираючись на ціпок, і подивився на юнака.',
        '— Магія вимагає плати, хлопче. Завжди.',
    ],
}


def write_wav(path, audio, rate):
    pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())


class Supertonic:
    """Python port of the official web/helper.js inference loop (MIT, Supertone)."""

    def __init__(self, root, threads):
        import onnxruntime as ort
        options = ort.SessionOptions(); options.intra_op_num_threads = threads; options.inter_op_num_threads = 1
        load = lambda name: ort.InferenceSession(str(root / 'onnx' / name), options, providers=['CPUExecutionProvider'])
        self.dp, self.enc, self.vec, self.voc = (load(n) for n in ('duration_predictor.onnx', 'text_encoder.onnx', 'vector_estimator.onnx', 'vocoder.onnx'))
        self.cfg = json.loads((root / 'onnx' / 'tts.json').read_text('utf-8'))
        self.indexer = json.loads((root / 'onnx' / 'unicode_indexer.json').read_text('utf-8'))
        self.root = root; self.rate = self.cfg['ae']['sample_rate']

    def style(self, name):
        data = json.loads((self.root / 'voice_styles' / (name + '.json')).read_text('utf-8'))
        tensor = lambda key: np.array(data[key]['data'], dtype=np.float32).reshape(data[key]['dims'])
        return tensor('style_ttl'), tensor('style_dp')

    def text(self, value, lang):
        value = unicodedata.normalize('NFKD', value)
        for a, b in {'–': '-', '‑': '-', '—': '-', '_': ' ', '“': '"', '”': '"', '‘': "'", '’': "'", '«': '"', '»': '"'}.items():
            value = value.replace(a, b)
        value = re.sub(r'\s+', ' ', value).strip()
        if not re.search(r'[.!?;:,\'")\]}…]$', value):
            value += '.'
        return '<%s>%s</%s>' % (lang, value, lang)

    def __call__(self, value, lang, voice, steps=8, speed=1.05, seed=7):
        ttl, dp = self.style(voice)
        text = self.text(value, lang)
        ids = np.array([[self.indexer[ord(c)] if ord(c) < len(self.indexer) else -1 for c in text]], dtype=np.int64)
        mask = np.ones((1, 1, ids.shape[1]), dtype=np.float32)
        duration = self.dp.run(None, {'text_ids': ids, 'style_dp': dp, 'text_mask': mask})[0] / speed
        emb = self.enc.run(None, {'text_ids': ids, 'style_ttl': ttl, 'text_mask': mask})[0]
        chunk = self.cfg['ae']['base_chunk_size'] * self.cfg['ttl']['chunk_compress_factor']
        length = int((float(duration[0]) * self.rate + chunk - 1) // chunk)
        dim = self.cfg['ttl']['latent_dim'] * self.cfg['ttl']['chunk_compress_factor']
        rng = np.random.default_rng(seed)
        xt = rng.standard_normal((1, dim, length)).astype(np.float32)
        latent_mask = np.ones((1, 1, length), dtype=np.float32)
        total = np.array([steps], dtype=np.float32)
        for step in range(steps):
            xt = self.vec.run(None, {'noisy_latent': xt, 'text_emb': emb, 'style_ttl': ttl, 'latent_mask': latent_mask,
                                     'text_mask': mask, 'current_step': np.array([step], dtype=np.float32), 'total_step': total})[0]
        wav = self.voc.run(None, {'latent': xt})[0].reshape(-1)
        return wav[:int(float(duration[0]) * self.rate)], self.rate


class Piper:
    def __init__(self, path, speaker=None):
        from piper import PiperVoice
        self.voice = PiperVoice.load(str(path)); self.speaker = speaker; self.rate = self.voice.config.sample_rate

    def __call__(self, value, lang, voice=None, **_):
        from piper import SynthesisConfig
        config = SynthesisConfig(speaker_id=self.speaker) if self.speaker is not None else None
        chunks = [c.audio_float_array for c in self.voice.synthesize(value, syn_config=config)]
        return np.concatenate(chunks), self.rate


def normalise(text):
    text = unicodedata.normalize('NFC', text).casefold().replace('ё', 'е').replace('’', "'").replace('ʼ', "'")
    return re.sub(r'\s+', ' ', re.sub(r"[^\w' ]+", ' ', text)).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--whisper', default='large-v3-turbo')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    engines = []
    for variant in ('fp32', 'int8', 'q4'):
        if (args.models / variant / 'onnx').exists():
            for steps in (5, 8):
                engines.append(('supertonic3-%s-s%d' % (variant, steps), lambda v=variant: Supertonic(args.models / v, args.threads),
                                {'ru': ['F1', 'M2'], 'uk': ['F1', 'M2']}, {'steps': steps}))
    piper_dir = args.models / 'piper'
    for name, lang, speaker in (('ru_RU-irina-medium', 'ru', None), ('ru_RU-denis-medium', 'ru', None),
                                ('uk_UA-ukrainian_tts-medium', 'uk', 0), ('uk_UA-lada-x_low', 'uk', None)):
        if (piper_dir / (name + '.onnx')).exists():
            engines.append(('piper-' + name, lambda n=name, s=speaker: Piper(piper_dir / (n + '.onnx'), s), {lang: [None]}, {}))
    rows = []
    for label, factory, voices, options in engines:
        started = time.perf_counter(); engine = factory(); load = time.perf_counter() - started
        for lang, names in voices.items():
            for voice in names:
                for index, sentence in enumerate(SENTENCES[lang]):
                    began = time.perf_counter(); audio, rate = engine(sentence, lang, voice, **options); took = time.perf_counter() - began
                    path = args.out / ('%s_%s_%s_%02d.wav' % (label, lang, voice or 'default', index))
                    write_wav(path, audio, rate)
                    rows.append({'engine': label, 'lang': lang, 'voice': voice, 'index': index, 'seconds': len(audio) / rate,
                                 'synthesis': took, 'rtf': took / max(.01, len(audio) / rate), 'load': load, 'wav': path.name, 'text': sentence})
        print(label, 'done', flush=True)
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(args.whisper, device='cuda', compute_type='float16')
    except Exception:
        model = WhisperModel(args.whisper, device='cpu', compute_type='int8')
    from jiwer import cer
    for row in rows:
        segments, _ = model.transcribe(str(args.out / row['wav']), language=row['lang'], beam_size=5, condition_on_previous_text=False)
        row['heard'] = ' '.join(s.text for s in segments).strip()
        row['cer'] = cer(normalise(row['text']), normalise(row['heard']))
    (args.out / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), 'utf-8')
    summary = {}
    for row in rows:
        key = (row['engine'], row['lang'])
        bucket = summary.setdefault(key, {'cer': [], 'rtf': []})
        bucket['cer'].append(row['cer']); bucket['rtf'].append(row['rtf'])
    print('engine | lang | mean CER | median RTF (CPU threads=%d)' % args.threads)
    for (engine, lang), bucket in sorted(summary.items()):
        print('%s | %s | %.3f | %.3f' % (engine, lang, float(np.mean(bucket['cer'])), float(np.median(bucket['rtf']))))


if __name__ == '__main__':
    main()
