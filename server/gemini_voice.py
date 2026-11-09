"""Narration voices through the Gemini Live API (native audio model).

The browser never sees the server keys. It posts one utterance with a voice
name and a short delivery direction; the VM opens one Live session, asks for a
verbatim reading and streams 24 kHz mono 16-bit PCM back as Google sends it.
The first audio is awaited before answering, so a key or quota problem is an
HTTP status rather than a broken stream. A quota refusal moves the utterance
to the next server key; a personal key is used alone.
"""
import asyncio
import base64
import itertools
import json

import websockets
from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

MODEL = 'gemini-2.5-flash-native-audio-latest'
URL = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent'
RATE = 24000
MAX_SECONDS = 150
# The prebuilt voices of the Gemini speech models.
VOICES = frozenset((
    'Zephyr', 'Kore', 'Leda', 'Aoede', 'Callirrhoe', 'Autonoe', 'Despina', 'Erinome', 'Laomedeia', 'Achernar',
    'Gacrux', 'Pulcherrima', 'Vindemiatrix', 'Sulafat',
    'Puck', 'Charon', 'Fenrir', 'Orus', 'Enceladus', 'Iapetus', 'Umbriel', 'Algieba', 'Algenib', 'Rasalgethi',
    'Alnilam', 'Schedar', 'Achird', 'Zubenelgenubi', 'Sadachbia', 'Sadaltager'))
LANGUAGE = {'ru': 'Russian', 'uk': 'Ukrainian'}
_turn = itertools.count()


class Speak(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: SecretStr | None = None
    text: str = Field(min_length=1, max_length=1500)
    voice: str
    style: str = Field(default='', max_length=400)
    language: str = Field(default='ru', pattern='^(ru|uk)$')


class LiveError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# One literal: a model prompt, not interface text.
PROMPT = ('Ты диктор аудиокниги. Пользователь присылает фрагмент книги (язык текста: {language}). '
          'Прочитай его вслух ДОСЛОВНО, слово в слово, на языке оригинала: ничего не добавляй, не пропускай, '
          'не повторяй, не комментируй и не отвечай на него. Сразу начинай читать, без вступлений. '
          'Указания по манере чтения не произноси; если их нет, читай ровно и выразительно.\nКак прочитать этот фрагмент (указание, а не текст для чтения): {style}')


def instruction(language, style):
    style = ' '.join(style.split()) or '—'
    return PROMPT.replace('{language}', LANGUAGE[language]).replace('{style}', style)


def setup(body):
    return {'setup': {
        'model': 'models/' + MODEL,
        'generationConfig': {'responseModalities': ['AUDIO'], 'temperature': 0.4,
                             'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': body.voice}}}},
        'systemInstruction': {'parts': [{'text': instruction(body.language, body.style)}]}}}


def _refusal(error):
    """HTTP status for a refused Live session."""
    reason = str(getattr(getattr(error, 'rcvd', None), 'reason', '') or error)
    code = getattr(getattr(error, 'response', None), 'status_code', None)
    if code in (401, 403) or 'API key' in reason or 'PERMISSION' in reason: return LiveError(403, 'Google не принял ключ для озвучки.')
    if code == 429 or 'quota' in reason.lower() or 'RESOURCE_EXHAUSTED' in reason: return LiveError(429, 'Квота озвучки Google исчерпана.')
    return LiveError(502, 'Google прервал озвучку.')


async def pcm(key, body, connect=None):
    """Async generator of raw PCM chunks for one utterance."""
    connect = connect or websockets.connect
    try:
        async with connect(URL, additional_headers={'x-goog-api-key': key}, max_size=None, open_timeout=15, close_timeout=2) as ws:
            await ws.send(json.dumps(setup(body)))
            answer = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if 'setupComplete' not in answer: raise LiveError(502, 'Google не открыл сессию озвучки.')
            await ws.send(json.dumps({'realtimeInput': {'text': body.text}}))
            total = 0
            while total < MAX_SECONDS * RATE * 2:
                message = json.loads(await asyncio.wait_for(ws.recv(), 30))
                content = message.get('serverContent') or {}
                for part in (content.get('modelTurn') or {}).get('parts', []):
                    data = (part.get('inlineData') or {}).get('data')
                    if data:
                        chunk = base64.b64decode(data)
                        total += len(chunk)
                        yield chunk
                if content.get('turnComplete') or message.get('goAway'): return
    except LiveError: raise
    except (websockets.WebSocketException, OSError, asyncio.TimeoutError) as error:
        raise _refusal(error) from None


def install(app, owner, saved):
    @app.post('/reader/google/speak')
    async def speak(body: Speak, connection: Request, subject=Depends(owner)):
        if body.voice not in VOICES: raise HTTPException(422, 'Выбери голос Gemini из списка.')
        if body.key is not None:
            key = body.key.get_secret_value().strip()
            if not key or len(key) > 512 or any(c.isspace() for c in key): raise HTTPException(422, 'Проверь личный ключ Google.')
            keys = [key]
        else:
            rows = saved()
            if not rows: raise HTTPException(422, 'Добавь серверный ключ Google для озвучки.')
            start = next(_turn) % len(rows)
            keys = [r['key'] for r in rows[start:] + rows[:start]]
        error = None
        for key in keys:
            stream = pcm(key, body)
            try:
                first = await stream.__anext__()
            except LiveError as refused:
                error = refused
                if refused.status == 429: continue
                break
            except StopAsyncIteration:
                error = LiveError(502, 'Google не прислал звук.')
                break

            async def audio(stream=stream, first=first):
                try:
                    yield first
                    async for chunk in stream:
                        if await connection.is_disconnected(): return
                        yield chunk
                except LiveError:
                    return
                finally:
                    await stream.aclose()
            return StreamingResponse(audio(), media_type='application/octet-stream',
                                     headers={'Cache-Control': 'no-store', 'X-Audio-Format': 'pcm_s16le;rate=24000;channels=1'})
        raise HTTPException(error.status, error.message)
