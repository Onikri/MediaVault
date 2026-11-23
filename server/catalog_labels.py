"""Repair catalogue labels damaged by an accidental UTF-8 legacy decode."""
import re
import unicodedata

_LATIN_MOJIBAKE=re.compile(r'(?:[ÐÑ][^\s]){2,}')
_CYRILLIC_MOJIBAKE=re.compile(r'(?:[РС][^\s]){2,}')
_ODD=set('Ѓ‚љњћџђѓєѕіїјќў€™')

def _badness(value):
    controls=sum(unicodedata.category(char) in {'Cc','Cs'} for char in value)
    symbols=sum(unicodedata.category(char).startswith(('S','M')) for char in value)
    letters=sum(char.isalpha() for char in value)
    return (controls*20+value.count('\ufffd')*20+
            len(_LATIN_MOJIBAKE.findall(value))*12+
            len(_CYRILLIC_MOJIBAKE.findall(value))*12+
            sum(char in _ODD for char in value)*3+max(0,symbols-letters//3))

def _utf8(value,encoding):
    try:return value.encode(encoding).decode('utf-8')
    except (UnicodeEncodeError,UnicodeDecodeError):return None

def readable_label(value):
    """Undo up to three common mojibake passes without changing clean text."""
    if not isinstance(value,str):return ''
    best=value.strip(' \t\r\n,;|')
    for _ in range(3):
        choices=[best]
        for encoding in ('latin1','cp1251'):
            candidate=_utf8(best,encoding)
            if candidate is not None:choices.append(candidate)
        candidate=min(choices,key=lambda text:(_badness(text),-sum(c.isalpha() for c in text),len(text)))
        if _badness(candidate)>=_badness(best):break
        best=candidate
    return ' '.join(best.split())[:120]
