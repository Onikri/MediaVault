"""Strict box/translation contracts. The VLM never supplies trusted coordinates."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = 1
MODEL_IDS = ('gemma-4-31b-it', 'gemma-4-26b-a4b-it')

class Translation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    uid: str = Field(pattern=r'^P[1-9][0-9]{0,5}_B[1-9][0-9]{0,3}$')
    source_lang: Literal['en','ja','ko','zh']
    text_category: Literal['dialogue','thought','narration','whisper_aside','sfx','system_ui','sign']
    font_style: Literal['standard_comic','bold_scream','handwritten_sloppy','serif_serious','digital_box','sfx_art']
    speech_register: Literal['casual_slang','neutral_conversational','formal_business','archaic_noble','panicked_broken']
    speaker_gender: Literal['male','female','neutral','unknown']
    connected_to_uid: str | None = None
    source_text: str = Field(max_length=4096)
    ru_translation: str = Field(max_length=4096)

TRANSLATIONS = TypeAdapter(list[Translation])

def validate_reply(value, expected):
    rows = TRANSLATIONS.validate_python(value)
    ids = [r.uid for r in rows]
    expected = set(expected)
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError('Model omitted, repeated or invented a box ID')
    for row in rows:
        if row.connected_to_uid and (row.connected_to_uid not in expected or row.connected_to_uid == row.uid):
            raise ValueError('Invalid dialogue connection')
        if row.source_text.strip() and not row.ru_translation.strip():
            raise ValueError('Empty translation for recognized text')
    links = {r.uid:r.connected_to_uid for r in rows if r.connected_to_uid}
    for uid in links:
        seen = set(); current = uid
        while current in links:
            if current in seen: raise ValueError('Cyclic dialogue connection')
            seen.add(current); current = links[current]
    return {r.uid:r.model_dump() for r in rows}

def generation_schema(expected_ids=None):
    # Google's uppercase schema is kept explicit: no unsupported Pydantic $defs.
    props = {}
    for name,field in Translation.model_fields.items():
        enum = getattr(field.annotation, '__args__', ())
        props[name] = {'type':'STRING'}
        if enum and all(isinstance(v,str) for v in enum): props[name]['enum'] = list(enum)
    props['connected_to_uid'] = {'type':'STRING','nullable':True}
    if expected_ids:
        # Constrain the actual IDs, not just their shape: some models otherwise
        # mistake text/punctuation in the picture for the visual box label.
        props['uid']['enum'] = list(expected_ids)
        props['connected_to_uid']['enum'] = list(expected_ids)
    return {'type':'ARRAY',**({'minItems':len(expected_ids),'maxItems':len(expected_ids)} if expected_ids else {}),'items':{'type':'OBJECT','required':[n for n,f in Translation.model_fields.items() if f.is_required()], 'properties':props}}
