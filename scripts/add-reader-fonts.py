"""Bundle four OFL fonts; verify Cyrillic and record immutable provenance."""
from pathlib import Path
import urllib.request,hashlib,json,io
from fontTools.ttLib import TTFont
root=Path(__file__).resolve().parents[1]/'reader-fonts'
revision=json.load(urllib.request.urlopen('https://api.github.com/repos/google/fonts/commits/main',timeout=20))['sha']
manifest=json.loads((root/'manifest.json').read_text())
for identity,folder,name in [('ruslan-display','ruslandisplay','RuslanDisplay-Regular.ttf'),('marck-script','marckscript','MarckScript-Regular.ttf'),('press-start','pressstart2p','PressStart2P-Regular.ttf'),('pt-serif','ptserif','PT_Serif-Web-Regular.ttf')]:
    if any(v['id']==identity for v in manifest):continue
    base='https://raw.githubusercontent.com/google/fonts/'+revision+'/ofl/'+folder+'/'
    raw=urllib.request.urlopen(base+name,timeout=20).read();font=TTFont(io.BytesIO(raw))
    glyphs='АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя'
    assert all(ord(c) in font.getBestCmap() for c in glyphs),identity
    font.flavor='woff2';out=io.BytesIO();font.save(out);packed=out.getvalue()
    (root/(identity+'.woff2')).write_bytes(packed)
    (root/(identity+'-OFL.txt')).write_bytes(urllib.request.urlopen(base+'OFL.txt',timeout=20).read())
    manifest.append({'id':identity,'weight':400,'source':base+name,'sourceSHA256':hashlib.sha256(raw).hexdigest(),'file':identity+'.woff2','bytes':len(packed),'sha256':hashlib.sha256(packed).hexdigest(),'russianGlyphsVerified':len(glyphs),'license':'SIL Open Font License 1.1'})
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Four OFL fonts added; Russian glyph coverage verified.')
