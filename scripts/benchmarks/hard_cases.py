#!/usr/bin/env python3
"""Private upstream test pages with explicit provenance and dialogue labels.
Images are downloaded into the benchmark directory, never redistributed in Git.
Korean signs/SFX are unlabelled, so detector precision must not be scored there.
"""
import argparse,hashlib,json
from pathlib import Path
import requests,cv2,numpy as np
from PIL import Image
REV='39a95be1890e2ea3e227052976bbaf576a8eb7b3'
SPECS=[('jp-vertical','Japanese','vertical-japanese-test.png','58774e40995de1e2bd74713570a05d6b966776c4e8da671204fa19452900a76e',[[2806,604,3119,1031],[539,414,896,914],[2167,1804,2498,2378],[402,700,580,1041]],['これはあたしとセラの冒険のお話','いつかまた家族として一緒になれるように！','苦しみと喜びを分かち合いながらあたしたちはこの分断された世界を旅してる','はじまりはじまり～']),('ko-dialogue','Korean','korean-test.png','6d84f710f88de31adc1294c3ad6d669cb4b47d9e2e75e4abf73e13d1d88f8097',[[300,1330,470,1500],[877,1220,1085,1380]],['코엔지역은 이리로 가면 될까?','저기... 총각 뭐 좀 물어볼게'])]
def generate(output):
 root=Path(output);root.mkdir(parents=True,exist_ok=True);cases=[]
 for id,lang,name,sha,boxes,texts in SPECS:
  p=root/name;url=f'https://raw.githubusercontent.com/mrdhnto/libre-manga-translator/{REV}/tests/assets/{name}'
  if not p.exists():r=requests.get(url,timeout=60);r.raise_for_status();p.write_bytes(r.content)
  assert hashlib.sha256(p.read_bytes()).hexdigest()==sha
  image=Image.open(p).convert('RGB');regions=[]
  for box,text in zip(boxes,texts):
   if lang=='Japanese':
    # Get text pixels inside known white narration rectangles. Discard border
    # components from an overlapping narration panel, not thin Japanese glyphs.
    x1,y1,x2,y2=box;x1+=16;y1+=16;x2-=16;y2-=16;gray=np.asarray(image.convert('L'))[y1:y2,x1:x2];n,labels,stats,centers=cv2.connectedComponentsWithStats((gray<160).astype(np.uint8));keep=[i for i in range(1,n) if stats[i,4]>=4 and max(stats[i,2]/max(1,stats[i,3]),stats[i,3]/max(1,stats[i,2]))<18]
    yy,xx=np.where(np.isin(labels,keep));assert len(xx)>0;box=[int(xx.min()+x1-4),int(yy.min()+y1-4),int(xx.max()+x1+5),int(yy.max()+y1+5)]
   regions.append({'box':box,'text':text})
  cases.append({'id':id,'language':lang,'file':name,'width':image.width,'height':image.height,'regions':regions,'kind':'upstream-real-test-page','source':url,'sha256':sha,'partialAnnotations':lang=='Korean','annotationNotes':'Korean dialogue boxes only; SFX/signs unlabelled. Japanese labels use the four upstream e2e narration references.'})
 (root/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n');return cases
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps({'cases':len(generate(a.output))}))
