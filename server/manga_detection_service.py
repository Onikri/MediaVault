# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private Docker-network service, no public route/host port and no Drive mounts."""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Literal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image

app=FastAPI();lock=asyncio.Lock();Image.MAX_IMAGE_PIXELS=24_000_000
class Body(BaseModel):
    model_config=ConfigDict(extra='forbid')
    image:str=Field(min_length=20,max_length=14*1024*1024)
    textModel:Literal['none','magi']='none'
    panelModel:Literal['none','yolov12-panels']='none'

@app.get('/status')
async def status():
    return {'models':[model for model,file in [('magi','magi/model.safetensors'),('yolov12-panels','yolov12/best.pt')] if Path('/models',file).is_file()]}

async def infer(model,source,destination):
    proc=await asyncio.create_subprocess_exec(sys.executable,'/app/manga_detection_worker.py',model,str(source),str(destination),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE,start_new_session=True)
    try:
        _,error=await asyncio.wait_for(proc.communicate(),180)
        if proc.returncode:raise HTTPException(503,'Детектор '+model+' завершился с ошибкой: '+error.decode(errors='replace')[-500:])
        return json.loads(destination.read_text())
    finally:
        if proc.returncode is None:
            os.killpg(proc.pid,signal.SIGKILL);await proc.wait()

@app.post('/detect')
async def detect(body:Body):
    try:
        data=base64.b64decode(body.image,validate=True)
        if len(data)>10*1024*1024:raise ValueError('Image too large')
        with Image.open(io.BytesIO(data)) as im:
            if im.width*im.height>24_000_000:raise ValueError('Image too large')
            im.verify()
    except Exception:raise HTTPException(400,'Invalid page')
    if lock.locked():raise HTTPException(429,'Детектор занят предыдущей страницей.')
    async with lock:
        with tempfile.TemporaryDirectory(prefix='manga-') as temp:
            root=Path(temp);source=root/'page';source.write_bytes(data);out={'text':[],'panels':[],'stages':[]}
            for model in [body.textModel,body.panelModel]:
                if model=='none':continue
                result=await infer(model,source,root/'result.json')
                if model=='magi':out['text']=result['text'];out['panels']=result['panels']
                else:out['panels']=result['panels']
                out['stages'].append({k:v for k,v in result.items() if k not in {'text','panels'}})
            return out
