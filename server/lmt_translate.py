# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct local translation, one complete source segment per response."""
from __future__ import annotations
import os
import re
import httpx


class SegmentTranslator:
    def __init__(self, profile=None):
        self.profile = profile or os.getenv('LMT_LLM_PROFILE', 'hymt2')

    async def _complete(self, prompt, budget):
        headers = {'Content-Type': 'application/json'}
        if os.getenv('LMT_LLM_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['LMT_LLM_API_KEY']
        model = os.environ.get('LMT_INDEX_MODEL') if self.profile == 'index' else os.environ['LMT_LLM_MODEL']
        if not model:
            raise ValueError('Index Translate не установлен на этой ВМ.')
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.7, 'top_p': 0.6, 'top_k': 20, 'repeat_penalty': 1.05,
                'max_tokens': budget, 'stream': False, 'seed': 42, 'chat_template_kwargs': {'enable_thinking': False}}
        if self.profile == 'index':
            body['temperature'] = 0
            for key in ('top_p', 'top_k', 'repeat_penalty'):
                body.pop(key)
        async with httpx.AsyncClient(timeout=180, trust_env=False, follow_redirects=False) as client:
            response = await client.post(os.environ['LMT_LLM_URL'].rstrip('/') + '/chat/completions', json=body, headers=headers)
            response.raise_for_status()
            choice = response.json()['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('Translation exceeded output budget')
        text = choice.get('message', {}).get('content', '').strip()
        if not text:
            raise ValueError('Translation model returned no text')
        return text

    async def translate(self, request):
        texts = request.get('texts')
        target = request.get('target', 'Russian')
        if not isinstance(texts, list) or len(texts) > 100 or any(not isinstance(t, str) for t in texts):
            raise ValueError('Invalid translation segments')
        if sum(map(len, texts)) > 12000 or not re.fullmatch(r'[A-Za-z -]{2,32}', target):
            raise ValueError('Translation input exceeds limit')
        active = [(i, t.strip()) for i, t in enumerate(texts) if t.strip()]
        translations = [''] * len(texts)
        context = request.get('context') or {}
        # Preserve supplied series terms and recent actual translations. Do not
        # spend tokens inventing an English synopsis on every page.
        info = '\n'.join(str(context.get(k, '')) for k in ('seriesName', 'summary', 'dictionary'))[:2000]
        history = '\n'.join(h.get('text', '') for h in context.get('recentHistory', [])[-2:])[-2000:]
        prefix = f'Reference context (do not translate):\n{info}\n{history}\n' if (info.strip() or history) else ''
        diagnostics = {'profile': self.profile, 'requests': 0, 'segmentFallbacks': 0}
        for index, source in active:
            diagnostics['requests'] += 1
            if self.profile == 'index':
                prompt = '请将以下文本翻译为俄语，直接输出翻译结果，不要进行任何解释。\n\n' + source
            elif self.profile == 'hymt2':
                prompt = f'Translate the following text into {target}. Note that you should only output the translated result without any additional explanation:\n\n' + source
            else:
                prompt = prefix + f'Translate the following segment into {target}, without additional explanation.\n\n{source}'
            translations[index] = await self._complete(prompt, min(1536, max(128, len(source) * 4)))
            if translations[index] == source and re.search(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]', source) and target == 'Russian':
                raise ValueError('Model returned untranslated source text')
        return {'translations': translations, 'context': context, 'translationDiagnostics': diagnostics}
