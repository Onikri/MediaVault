"""Repair catalogue labels damaged by an accidental UTF-8 legacy decode."""
import re
import unicodedata
from functools import lru_cache

_LATIN_MOJIBAKE=re.compile(r'(?:[ÐÑ][^\s]){2,}')
_CYRILLIC_MOJIBAKE=re.compile(r'(?:[РС][^\s]){2,}')
_ODD=set('Ѓ‚љњћџђѓєѕіїјќў€™')
# A source page decoded as one of these Mac code pages, then NFKC-normalized.
MAC_ENCODINGS=('mac_roman','mac_cyrillic','mac_greek')
# Scripts a repaired catalogue label may contain beyond ASCII.
_SCRIPTS=((0xC0,0x24F),(0x400,0x52F),(0x2010,0x206F),(0x3000,0x30FF),(0x3400,0x9FFF),(0xAC00,0xD7AF),(0xFF00,0xFFEF))

def _badness(value):
    controls=sum(unicodedata.category(char) in {'Cc','Cs'} for char in value)
    symbols=sum(unicodedata.category(char).startswith(('S','M')) for char in value)
    letters=sum(char.isalpha() for char in value)
    return (controls*20+value.count('�')*20+
            len(_LATIN_MOJIBAKE.findall(value))*12+
            len(_CYRILLIC_MOJIBAKE.findall(value))*12+
            sum(char in _ODD for char in value)*3+max(0,symbols-letters//3))

def _utf8(value,encoding):
    try:return value.encode(encoding).decode('utf-8')
    except (UnicodeEncodeError,UnicodeDecodeError):return None

def _mac_forms(encoding):
    """Text that one high byte (0x80-0xFF) becomes after a Mac decode and
    NFKC: µ→μ, º→o, ª→a, ™→TM, ¨→' ̈'. Bytes may share one form."""
    forms={}
    for byte in range(0x80,0x100):
        char=bytes([byte]).decode(encoding)
        for form in dict.fromkeys([char,unicodedata.normalize('NFKC',char)]):
            # Whitespace is collapsed by the label cleaner; never guess it.
            if form and not form.isspace():
                forms.setdefault(form,[])
                if byte not in forms[form]:forms[form].append(byte)
    first={}
    for form in forms:first.setdefault(form[0],[]).append(form)
    for values in first.values():values.sort(key=len,reverse=True)
    return forms,first

# One page is decoded with one code page, so each is tried on its own.
_TABLES={encoding:_mac_forms(encoding) for encoding in MAC_ENCODINGS}

def _lead(byte):
    if 0xC2<=byte<=0xDF:return 1
    if 0xE0<=byte<=0xEF:return 2
    if 0xF0<=byte<=0xF4:return 3
    return None

def mac_repair(value):
    """UTF-8 text that was read as Mac Roman/Cyrillic and then NFKC-normalized
    («–≤–μ–±» → «веб»), or None when the value is not such mojibake."""
    if not isinstance(value,str) or value.isascii() or len(value)>240:return None
    found=[text for encoding in MAC_ENCODINGS if (text:=_mac_decode(value,*_TABLES[encoding])) is not None]
    # Prefer the reading with the fewest scripts (all Cyrillic over mixed).
    return min(found,key=lambda text:len({_script(char) for char in text if char.isalpha()})) if found else None

def _script(char):
    return unicodedata.name(char,'?').split(' ')[0]

def _mac_decode(value,forms,first):
    size=len(value);failed=set()
    def walk(index,pending):
        # Bytes for value[index:], given continuation bytes still owed.
        if index==size:return [] if not pending else None
        if (index,pending) in failed:return None
        char=value[index];options=[]
        for form in first.get(char,()):
            if value.startswith(form,index):options+=[(len(form),byte,form.isascii()) for byte in forms[form]]
        if char.isascii():options.append((1,ord(char),False))
        for width,byte,collision in options:
            if pending:
                if not 0x80<=byte<=0xBF:continue
                following=pending-1
            elif byte<0x80:following=0
            elif (following:=_lead(byte)) is None:continue
            rest=walk(index+width,following)
            if rest is not None:return [(byte,collision),*rest]
        failed.add((index,pending))
        return None
    path=walk(0,0)
    if path is None:return None
    try:text=bytes(byte for byte,_ in path).decode('utf-8')
    except UnicodeDecodeError:return None
    if text==value or text.isascii():return None
    if any(ord(char)>0x7F and not any(low<=ord(char)<=high for low,high in _SCRIPTS) for char in text):return None
    # An ASCII letter read as a high byte (º→o) is a guess; most repaired
    # characters must come from high bytes alone («dell’arte» stays).
    wide=sum(ord(char)>0x7F for char in text)
    if 2*sum(collision for _,collision in path)>wide:return None
    letters=sum(char.isalpha() for char in text)
    # Real labels are mostly letters; the damaged form is mostly symbols.
    if not letters or letters/len(text)<=sum(char.isalpha() for char in value)/len(value):return None
    return unicodedata.normalize('NFC',text)

def readable_label(value):
    """Undo up to three common mojibake passes without changing clean text."""
    if not isinstance(value,str):return ''
    return _readable_label(value)


@lru_cache(maxsize=32768)
def _readable_label(value):
    best=value.strip(' \t\r\n,;|')
    repaired=mac_repair(best)
    if repaired is not None and _badness(repaired)<=_badness(best):best=repaired
    for _ in range(3):
        score=_badness(best)
        if not score:break
        choices=[best]
        for encoding in ('latin1','cp1251'):
            candidate=_utf8(best,encoding)
            if candidate is not None:choices.append(candidate)
        candidate=min(choices,key=lambda text:(_badness(text),-sum(c.isalpha() for c in text),len(text)))
        if _badness(candidate)>=score:break
        best=candidate
    return ' '.join(best.split())[:120]
