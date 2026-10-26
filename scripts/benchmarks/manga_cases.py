#!/usr/bin/env python3
"""Owned synthetic stress pages, with exact text/mask/background ground truth.
These fixtures test edge cases, not population accuracy on published manga.
"""
from pathlib import Path
import argparse,hashlib,io,json,math,os
from PIL import Image,ImageDraw,ImageFont,ImageFilter

TEXTS=[('I do not believe in aliens.','Я не верю в инопланетян.'),('Wait! Do not open that door.','Стой! Не открывай эту дверь.'),('Momo, are you all right?','Момо, ты в порядке?'),('We will meet again tomorrow.','Мы снова встретимся завтра.')]
def create(root):
 root=Path(root);root.mkdir(parents=True,exist_ok=True)
 font_path=next(f for f in ['/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if Path(f).exists())
 cases=[]
 for name in ['clean','adjacent','low-contrast','over-art','skewed','tall-webtoon']:
  w,h=(700,2300) if name=='tall-webtoon' else (900,1100)
  clean=Image.new('RGB',(w,h),'#eee6d8');d=ImageDraw.Draw(clean)
  for y in range(25,h,280):
   d.rectangle((18,y,w-18,min(h-15,y+260)),fill='#e3ded4',outline='black',width=4)
   for x in range(25,w,13):d.line((x,y+6,min(w-25,x+190),min(h-25,y+250)),fill='#b8b0a3',width=1)
  positions=[(70,80,360,250),(490,115,790,300),(85,440,390,620),(480,730,800,940)]
  if name=='adjacent':positions=[(45,70,430,280),(440,70,830,280),(45,450,430,680),(440,450,830,680)]
  if name=='tall-webtoon':positions=[(45,90,360,340),(350,690,650,930),(45,1320,380,1550),(340,1880,660,2130)]
  for j,b in enumerate(positions):
   if name!='over-art':d.ellipse(b,fill='#faf6ed' if name=='low-contrast' else 'white',outline='#a7a29a' if name=='low-contrast' else 'black',width=2)
  image=clean.copy();mask=Image.new('L',(w,h));ink=ImageDraw.Draw(image);md=ImageDraw.Draw(mask);regions=[]
  for j,(b,(text,ru)) in enumerate(zip(positions,TEXTS)):
   font=ImageFont.truetype(font_path,22 if name=='adjacent' else 25)
   words=text.upper().split();lines=[];line='';max_width=(b[2]-b[0])*.68
   for word in words:
    candidate=(line+' '+word).strip()
    if ink.textlength(candidate,font=font)>max_width and line:lines.append(line);line=word
    else:line=candidate
   lines.append(line);lh=34;yy=(b[1]+b[3]-lh*len(lines))/2;boxes=[]
   for line in lines:
    tw=ink.textlength(line,font=font);xx=(b[0]+b[2]-tw)/2
    box=ink.textbbox((xx,yy),line,font=font);boxes.append(box)
    ink.text((xx,yy),line,font=font,fill='#aaa299' if name=='low-contrast' else 'black');md.text((xx,yy),line,font=font,fill=255,stroke_width=2);yy+=lh
   tb=[int(min(x[0] for x in boxes))-3,int(min(x[1] for x in boxes))-3,int(max(x[2] for x in boxes))+3,int(max(x[3] for x in boxes))+3]
   regions.append({'box':tb,'bubble':list(b),'text':text.upper(),'referenceRu':ru})
  if name=='skewed':
   # Rotate input and exact hidden clean plate/mask together, preserving labels.
   angle=5;image=image.rotate(angle,Image.Resampling.BICUBIC,fillcolor='#eee6d8');clean=clean.rotate(angle,Image.Resampling.BICUBIC,fillcolor='#eee6d8');mask=mask.rotate(angle,Image.Resampling.NEAREST)
   a=math.radians(-angle)
   for r in regions:
    x1,y1,x2,y2=r['box'];points=[((x-w/2)*math.cos(a)-(y-h/2)*math.sin(a)+w/2,(x-w/2)*math.sin(a)+(y-h/2)*math.cos(a)+h/2) for x,y in [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]]
    r['box']=[math.floor(min(x for x,y in points)),math.floor(min(y for x,y in points)),math.ceil(max(x for x,y in points)),math.ceil(max(y for x,y in points))]
  file=name+'.png';image.save(root/file);clean.save(root/(name+'-clean.png'));mask.save(root/(name+'-mask.png'))
  cases.append({'id':name,'file':file,'width':w,'height':h,'regions':regions,'sha256':hashlib.sha256((root/file).read_bytes()).hexdigest(),'kind':'owned-synthetic'})
 # Language tests are printed prose, not a representative handwritten manga corpus.
 cjk=os.environ.get('MANGA_BENCH_CJK_FONT','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
 for lang,texts in [('Japanese',['私は宇宙人を信じていません。','その扉を開けないでください！']),('Korean',['나는 외계인을 믿지 않는다.','그 문을 열지 마세요!'])]:
  image=Image.new('RGB',(900,260),'white');d=ImageDraw.Draw(image);font=ImageFont.truetype(cjk,36);regions=[]
  for n,text in enumerate(texts):
   box=d.textbbox((30,30+100*n),text,font=font);d.text((30,30+100*n),text,font=font,fill='black');regions.append({'box':[box[0]-5,box[1]-5,box[2]+5,box[3]+5],'text':text})
  file=lang.lower()+'.png';image.save(root/file);cases.append({'id':lang.lower(),'language':lang,'file':file,'width':900,'height':260,'regions':regions,'sha256':hashlib.sha256((root/file).read_bytes()).hexdigest(),'kind':'owned-printed-language-smoke'})
 (root/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n');return cases
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',default='test-output/manga-quality/cases');a=p.parse_args();print(json.dumps({'cases':len(create(a.output)),'output':a.output}))
