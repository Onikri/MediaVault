"""Ranobe and book chapters voiced on the VM for Google Drive.

The owner's computer may be off. For every chapter the reader's own narration
director runs on the VM (narration_runtime: title bible, role pass with Gemini
Lite / Gemma, cast and the owner's voice choices sent with the job), and its
multi-voice script is voiced here phrase by phrase with the same Gemini 2.5
Flash Native Audio voices as the reader (gemini_voice). Short lines the Live
model leaves silent go to the 3.8 Flash speech model in the same voice, as in
the reader. The chapter becomes one Ogg Opus file, encrypted like every import.

Voiced phrases stay in an encrypted cache on the VM until the chapter is
written: a quota pause or a restart resumes the chapter instead of paying for
its phrases again. When every server key is out of quota (voice or role
model), the task goes back to the queue with a resume time (Paused).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time

from source_parser import SourceError

RATE = 24000
PARALLEL = 3


class Paused(Exception):
    """Every key is out of quota: continue the task later."""
    def __init__(self, seconds, message='Квота Google для озвучки исчерпана.'):
        super().__init__(message)
        self.seconds = seconds


class VoiceError(RuntimeError):
    """Google refused the voice itself (keys, model): stop the task with this message."""


class PhraseCache:
    """Voiced phrases, AES-GCM sealed with the service key, for one week."""
    def __init__(self, directory, maximum=384 * 1024**2):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.root = Path(directory) / '.codex-local' / 'audiobook-phrases'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = AESGCM((Path(directory) / 'service.key').read_bytes())
        self.maximum = maximum

    @staticmethod
    def key(scope, voice, style, language, text):
        return hashlib.sha256(json.dumps([1, scope, voice, style, language, text], ensure_ascii=False).encode()).hexdigest()

    def read(self, identity):
        path = self.root / (identity + '.pcm')
        try:
            if time.time() - path.stat().st_mtime > 7 * 86400:
                return None
            raw = path.read_bytes()
            return self.cipher.decrypt(raw[:12], raw[12:], identity.encode())
        except Exception:
            return None

    def write(self, identity, data):
        iv = secrets.token_bytes(12)
        path = self.root / (identity + '.pcm')
        temporary = path.with_suffix('.part')
        temporary.write_bytes(iv + self.cipher.encrypt(iv, data, identity.encode()))
        temporary.chmod(0o600)
        temporary.replace(path)
        self.prune()

    def forget(self, identities):
        for identity in identities:
            (self.root / (identity + '.pcm')).unlink(missing_ok=True)

    def prune(self):
        files = sorted(self.root.glob('*.pcm'), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        for value in files:
            if total <= self.maximum and time.time() - value.stat().st_mtime <= 7 * 86400:
                break
            total -= value.stat().st_size
            value.unlink(missing_ok=True)


def script_rows(script):
    """The director's rows, checked: known voices, bounded text and style."""
    import gemini_voice
    if not isinstance(script, dict):
        raise SourceError('Режиссёр озвучки не вернул сценарий главы.')
    if script.get('analysis') == 'failed':
        # Every role request failed (quota or network): voicing the bare
        # heuristic roles would give a worse chapter than the reader's.
        raise Paused(120, 'Квота Google для разметки ролей исчерпана.')
    rows = []
    for row in script.get('rows') or []:
        text = str(row.get('text') or '').strip()[:1500]
        voice = row.get('voice')
        if not text:
            continue
        if voice not in gemini_voice.VOICES:
            raise SourceError('Сценарий главы содержит неизвестный голос.')
        pause = row.get('pause') or 0
        rows.append({'text': text, 'voice': voice, 'style': str(row.get('style') or '')[:400],
                     'pause': max(0.0, min(3.0, float(pause) if isinstance(pause, (int, float)) else 0.0))})
    return rows


async def speak(keys, body, *, live=None, line=None, attempts=3, delay=2.0):
    """One phrase as 24 kHz 16-bit PCM, rotating the server keys like /reader/google/speak."""
    import gemini_voice
    live = live or gemini_voice.pcm
    line = line or gemini_voice.spoken_line
    if not keys:
        raise VoiceError('Добавь в профиле серверный ключ Google для озвучки.')
    for attempt in range(attempts):
        refusals = []
        silent = False
        for key in keys:
            data = bytearray()
            try:
                async for chunk in live(key, body):
                    data += chunk
            except gemini_voice.LiveError as refused:
                refusals.append(refused.status)
                continue
            if len(data) >= gemini_voice.MIN_AUDIO:
                return bytes(data[:len(data) & ~1])
            silent = True
            break
        if silent:
            # The Live model's answer to this line is silence on any key: the
            # speech model reads it, as in the reader.
            for key in keys:
                try:
                    return await line(key, body)
                except gemini_voice.LiveError as refused:
                    refusals.append(refused.status)
        if refusals and all(status == 429 for status in refusals):
            raise Paused(120)
        if refusals and all(status == 403 for status in refusals):
            raise VoiceError('Google не принял серверные ключи для озвучки. Проверь ключи в профиле.')
        if attempt < attempts - 1:
            await asyncio.sleep(delay * (attempt + 1))
    raise SourceError('Google не озвучил фразу главы. Готовые фразы сохранены, задание можно продолжить.')


def silence(seconds):
    return bytes(int(seconds * RATE) * 2)


def synthesize(rows, *, language, keys, scope='', cache=None, progress=lambda _: None,
               cancelled=lambda: False, parallel=PARALLEL, speak_phrase=speak):
    """The chapter's PCM in reading order, each row in its own voice and style.
    Returns (pcm, cached phrase identities)."""
    import gemini_voice
    if any(row['voice'] not in gemini_voice.VOICES for row in rows):
        raise VoiceError('Выбери голос Gemini из списка.')
    identities = [PhraseCache.key(scope, row['voice'], row['style'], language, row['text']) for row in rows]
    results = [None] * len(rows)

    async def run():
        semaphore = asyncio.Semaphore(max(1, parallel))
        done = 0

        async def one(index):
            nonlocal done
            if cache:
                results[index] = cache.read(identities[index])
            if results[index] is None:
                async with semaphore:
                    if cancelled():
                        raise SourceError('Импорт отменён владельцем.')
                    row = rows[index]
                    body = gemini_voice.Speak(text=row['text'], voice=row['voice'], style=row['style'], language=language)
                    results[index] = await speak_phrase(keys, body)
                    if cache:
                        cache.write(identities[index], results[index])
            done += 1
            progress({'phase': 'voicing', 'phrasesDone': done, 'phrasesTotal': len(rows),
                      'operation': f'Озвучиваем главу · {done} из {len(rows)} фраз'})

        tasks = [asyncio.create_task(one(index)) for index in range(len(rows))]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    asyncio.run(run())
    audio = bytearray()
    for row, data in zip(rows, results):
        audio += data
        audio += silence(row.get('pause', 0))
    return bytes(audio), identities


def encode_opus(pcm, target, *, tags=None, run=subprocess.run, bitrate='48k'):
    """24 kHz mono PCM → Ogg Opus with title/album/artist tags."""
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 's16le', '-ar', str(RATE), '-ac', '1', '-i', 'pipe:0']
    for key, value in (tags or {}).items():
        value = re.sub(r'[\x00-\x1f]', ' ', str(value or '')).strip()[:300]
        if value:
            command += ['-metadata', f'{key}={value}']
    command += ['-c:a', 'libopus', '-b:a', bitrate, '-application', 'audio', str(target)]
    result = run(command, input=pcm, capture_output=True, timeout=1800)
    if getattr(result, 'returncode', 1) != 0 or not Path(target).is_file() or Path(target).stat().st_size < 64:
        raise SourceError('Сервер не смог записать файл аудиокниги.')
    return Path(target)
