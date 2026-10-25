"""Private, bounded English OCR → Russian overlays. No paid/cloud translator."""
import base64,csv,hashlib,io,json,os,re,subprocess,tempfile,threading,time,zipfile
from pathlib import Path
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
MODEL_URL='https://argos-net.com/v1/translate-en_ru-1_9.argosmodel'
MODEL_SHA256='591d743ae103752b88ffc38785c50421320f4eff93c8967e0d3d2e14d4e27811'
MAX_IMAGE=10*1024*1024
slot=threading.BoundedSemaphore(1)
_engine=None
_cache={};_cache_lock=threading.RLock()

def model_root(data_dir):return Path(data_dir)/'reader-models'/'translate-en_ru-1_9'
def ready(data_dir):return (model_root(data_dir)/'model'/'model.bin').is_file()
def install_model(data_dir):
    import requests
    root=Path(data_dir)/'reader-models';root.mkdir(parents=True,exist_ok=True)
    if ready(data_dir):return
    with tempfile.TemporaryDirectory(prefix='model-',dir=root) as work:
        archive=Path(work)/'model.zip';digest=hashlib.sha256();total=0
        with requests.get(MODEL_URL,stream=True,timeout=(10,60)) as response:
            response.raise_for_status()
            with archive.open('wb') as out:
                for part in response.iter_content(1024*1024):
                    total+=len(part)
                    if total>230*1024*1024:raise ValueError('Model exceeds limit')
                    digest.update(part);out.write(part)
        if digest.hexdigest()!=MODEL_SHA256:raise ValueError('Translation model checksum mismatch')
        with zipfile.ZipFile(archive) as source:
            for name in source.namelist():
                # Stanza/Torch are unnecessary: this English OCR uses Tesseract.
                if name.startswith('translate-en_ru-1_9/model/') or name in {'translate-en_ru-1_9/sentencepiece.model','translate-en_ru-1_9/metadata.json','translate-en_ru-1_9/README.md'}:
                    if '..' in Path(name).parts or source.getinfo(name).file_size>230*1024*1024:raise ValueError('Invalid model archive')
                    source.extract(name,work)
        Path(work,'translate-en_ru-1_9').rename(model_root(data_dir))

def translate_texts(texts,data_dir):
    global _engine
    if _engine is None:
        import ctranslate2,sentencepiece
        tokenizer=sentencepiece.SentencePieceProcessor(model_file=str(model_root(data_dir)/'sentencepiece.model'))
        engine=ctranslate2.Translator(str(model_root(data_dir)/'model'),device='cpu',compute_type='int8',inter_threads=1,intra_threads=1)
        _engine=(tokenizer,engine)
    tokenizer,engine=_engine
    result=engine.translate_batch([tokenizer.encode(s,out_type=str) for s in texts],beam_size=2,max_decoding_length=256,max_input_length=256)
    return [tokenizer.decode(r.hypotheses[0]) for r in result]

def ocr_regions(tsv,width,height):
    groups={}
    for row in csv.DictReader(io.StringIO(tsv),delimiter='\t'):
        try:
            text=row.get('text','').strip();confidence=float(row.get('conf','-1'))
            x,y,w,h=(int(row[k]) for k in ('left','top','width','height'))
            if confidence<38 or not re.search('[A-Za-z]',text) or w<2 or h<3:continue
            key=(row['page_num'],row['block_num'],row['par_num'])
            groups.setdefault(key,[]).append((x,y,w,h,text,confidence))
        except (ValueError,KeyError,TypeError):continue
    result=[]
    for words in groups.values():
        text=' '.join(w[4] for w in words)
        short=text.strip(' .!?,:;').casefold()
        if len(text)>1500:continue
        if len(re.findall('[A-Za-z]',text))<3 and not (short in {'a','i','an','am','as','at','be','by','do','go','he','hi','if','in','is','it','me','my','no','of','oh','ok','on','or','so','to','up','us','we'} and min(w[5] for w in words)>=70):continue
        left=max(0,min(w[0] for w in words)-3);top=max(0,min(w[1] for w in words)-3)
        right=min(width,max(w[0]+w[2] for w in words)+3);bottom=min(height,max(w[1]+w[3] for w in words)+3)
        if right<=left or bottom<=top:continue
        result.append({'x':left/width,'y':top/height,'w':(right-left)/width,'h':(bottom-top)/height,'original':text})
    return result[:300]

def merge_bubbles(regions):
    # PSM 11 often returns each printed line as a separate block. Translating
    # those fragments independently loses negations and names. Join only close,
    # aligned lines, while keeping neighbouring columns/panels separate.
    groups=[]
    for region in sorted(regions,key=lambda r:(r['y'],r['x'])):
        candidates=[]
        for group in groups:
            last=group[-1];gap=region['y']-(last['y']+last['h']);height=max(last['h'],region['h'])
            overlap=min(last['x']+last['w'],region['x']+region['w'])-max(last['x'],region['x'])
            center=abs(last['x']+last['w']/2-region['x']-region['w']/2)
            if sum(len(r['original']) for r in group)+len(region['original'])<=1500 and -.5*height<=gap<=1.1*height and overlap>=.5*min(last['w'],region['w']) and center<=max(.02,.45*max(last['w'],region['w'])):
                candidates.append((abs(gap)+center,group))
        if candidates:min(candidates,key=lambda v:v[0])[1].append(region)
        else:groups.append([region])
    result=[]
    for group in groups:
        left=min(r['x'] for r in group);top=min(r['y'] for r in group)
        right=max(r['x']+r['w'] for r in group);bottom=max(r['y']+r['h'] for r in group)
        text=group[0]['original']
        for row in group[1:]:
            following=row['original'];text=text[:-1]+following if re.search(r'[A-Za-z]-$',text) and re.match('[A-Za-z]',following) else text+' '+following
        result.append({'x':left,'y':top,'w':right-left,'h':bottom-top,'original':text})
    return result[:60]

def translation_input(text):
    text=text.translate(str.maketrans({'’':"'",'‘':"'",'“':'"','”':'"'}))
    letters=re.findall('[A-Za-z]',text)
    if letters and sum(c.isupper() for c in letters)/len(letters)>.8:text=text.capitalize()
    acronyms={'ufo':'UFO','ufos':'UFOs','uap':'UAP','uaps':'UAPs','dna':'DNA','nasa':'NASA','fbi':'FBI','cia':'CIA','tv':'TV','usa':'USA','gps':'GPS'}
    text=re.sub(r'\b(?:UFOs?|UAPs?|DNA|NASA|FBI|CIA|TV|USA|GPS)\b',lambda m:acronyms[m[0].lower()],text,flags=re.I)
    return re.sub(r'\bi\b','I',text)

def refine_bubbles(image,regions,work):
    # A second OCR pass treats each detected speech bubble as one text block.
    # This recovers short/missed lines between the first and last detected rows.
    targets=[];paths=[]
    for index,region in enumerate(regions):
        if region['h']<.028 or len(region['original'])<9:continue
        left=max(0,int(region['x']*image.width)-7);top=max(0,int(region['y']*image.height)-7)
        right=min(image.width,int((region['x']+region['w'])*image.width)+7);bottom=min(image.height,int((region['y']+region['h'])*image.height)+7)
        path=Path(work)/('bubble-'+str(index)+'.png');image.crop((left,top,right,bottom)).save(path);paths.append(str(path));targets.append(index)
        if len(targets)>=40:break
    if not targets:return regions
    filelist=Path(work)/'bubbles.txt';filelist.write_text('\n'.join(paths)+'\n')
    try:
        output=subprocess.run(['tesseract',str(filelist),'stdout','-l','eng','--psm','6','tsv'],capture_output=True,timeout=20,check=False,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
        if output.returncode:return regions
        pages={}
        for row in csv.DictReader(io.StringIO(output.stdout.decode('utf-8','replace')),delimiter='\t'):
            try:
                text=row.get('text','').strip();confidence=float(row.get('conf','-1'));page=int(row['page_num'])
                if confidence<30 or not re.search('[A-Za-z]',text):continue
                pages.setdefault(page,[]).append((text,confidence,row.get('line_num')))
            except (ValueError,TypeError,KeyError):continue
        for page,words in pages.items():
            if not 1<=page<=len(targets) or sum(w[1] for w in words)/len(words)<50:continue
            text=''
            for word,confidence,line in words:
                text=text[:-1]+word if re.search(r'[A-Za-z]-$',text) and re.match('[A-Za-z]',word) else (text+' '+word).strip()
            target=regions[targets[page-1]]
            if len(target['original'])/2<=len(text)<=1500:target['original']=text
    except (OSError,subprocess.SubprocessError):pass
    return regions

def translate_image(data,data_dir):
    from PIL import Image,ImageOps
    Image.MAX_IMAGE_PIXELS=24_000_000
    try:
        image=Image.open(io.BytesIO(data));
        if image.width*image.height>24_000_000:raise ValueError('Image exceeds pixel limit')
        image.load();image=ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((1800,6000));width,height=image.size
    except Exception:raise HTTPException(422,'Не удалось прочитать страницу. Допустимы JPG, PNG и WebP до 24 Мп.') from None
    with tempfile.TemporaryDirectory(prefix='mv-ocr-') as work:
        path=Path(work)/'page.png';image.save(path)
        try:
            result=subprocess.run(['tesseract',str(path),'stdout','-l','eng','--psm','11','tsv'],capture_output=True,timeout=20,check=False,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
            if result.returncode:raise ValueError()
            regions=refine_bubbles(image,merge_bubbles(ocr_regions(result.stdout.decode('utf-8','replace'),width,height)),work)
            if regions:
                translated=translate_texts([translation_input(r['original']) for r in regions],data_dir)
                for region,text in zip(regions,translated):region['text']=text
            return {'regions':regions,'sourceLanguage':'en','targetLanguage':'ru','machineTranslation':True}
        except Exception:raise HTTPException(503,'OCR или перевод временно недоступен. Оригинал страницы сохранён.') from None

def install(app,data_dir,owner):
    class Body(BaseModel):
        model_config=ConfigDict(extra='forbid')
        image:str=Field(min_length=20,max_length=14*1024*1024)
    @app.get('/reader/translation')
    def status():return {'ready':ready(data_dir),'sourceLanguage':'en','targetLanguage':'ru','message':'Модель EN → RU установлена.' if ready(data_dir) else 'Модель перевода ещё не установлена на сервере.'}
    @app.post('/reader/translate')
    def translate(body:Body,subject=Depends(owner)):
        if not ready(data_dir):raise HTTPException(503,'Модель перевода ещё не установлена на сервере.')
        try:data=base64.b64decode(body.image,validate=True)
        except ValueError:raise HTTPException(422,'Некорректная страница.') from None
        if len(data)>MAX_IMAGE:raise HTTPException(413,'Страница превышает лимит 10 МБ.')
        key=(subject,hashlib.sha256(data).digest())
        with _cache_lock:hit=_cache.get(key)
        if hit and hit[0]>time.monotonic():return hit[1]
        if not slot.acquire(blocking=False):raise HTTPException(429,'Другая страница переводится. Повтори через несколько секунд.')
        try:
            result=translate_image(data,data_dir)
            with _cache_lock:
                _cache[key]=(time.monotonic()+21600,result)
                while len(_cache)>128:_cache.pop(next(iter(_cache)))
            return result
        finally:slot.release()
if __name__=='__main__':
    install_model(os.getenv('DATA_DIR','/data'));print('English → Russian model verified and installed.')
