"""Set-of-Mark copies are encoded in RAM and never returned as reader pages."""
from __future__ import annotations
import io
import time
from PIL import Image, ImageDraw, ImageFont

def compose(image, regions):
    start=time.perf_counter();scale=min(1,1280/max(image.size))
    size=(max(1,round(image.width*scale)),max(1,round(image.height*scale)))
    marked=image.resize(size,Image.Resampling.LANCZOS)
    draw=ImageDraw.Draw(marked);font=ImageFont.load_default(size=13)
    for region in regions:
        # A shared balloon can contain several distinct texts. Put each label
        # near its text, not repeatedly at the same balloon's top-left corner.
        b=region['text_bbox'];box=[round(v*scale) for v in b]
        draw.rectangle(box,outline='#FF0033',width=2)
        label=region['uid'];bounds=draw.textbbox((0,0),label,font=font)
        w,h=bounds[2]+6,bounds[3]-bounds[1]+5
        x=max(0,min(size[0]-w,box[0]));y=max(0,box[1]-h)
        draw.rectangle((x,y,x+w,y+h),fill='#FF0033');draw.text((x+3,y+2-bounds[1]),label,font=font,fill='white')
    out=io.BytesIO();marked.save(out,format='WEBP',quality=80,method=2);marked.close()
    return out.getvalue(),{'somMs':round((time.perf_counter()-start)*1000,2),'somBytes':out.tell(),'somWidth':size[0],'somHeight':size[1]}
