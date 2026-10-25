"""Run actual installed PTH models on a small pattern; not a quality benchmark."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('MKL_NUM_THREADS','2')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from PIL import Image,ImageDraw
from manga_upscale import Upscaler,model_catalog

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--models',type=Path,default=ROOT/'.codex-local/models/mangajanai')
parser.add_argument('--output',type=Path,default=ROOT/'.codex-local/benchmark/model-runtime-smoke.json')
args=parser.parse_args()
image=Image.new('RGB',(91,73),'white');draw=ImageDraw.Draw(image)
draw.ellipse((7,7,83,65),outline='black',width=2);draw.text((20,30),'MANGA',fill='black')
upscaler=Upscaler(args.models,'cpu');results=[]
for model in model_catalog(args.models):
    if model['format'] not in {'pth','safetensors'}:continue
    started=time.perf_counter()
    output,info=upscaler.run(image,{'model':model['id'],'tile':128})
    assert output.size==(image.width*model['scale'],image.height*model['scale'])
    result={**info,'seconds':round(time.perf_counter()-started,3),'sha256':hashlib.sha256(output.tobytes()).hexdigest()}
    results.append(result);print(json.dumps(result),flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps({'scope':'real inference; small pattern; not quality evaluation','models':results},indent=2)+'\n')
