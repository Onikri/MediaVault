// SPDX-License-Identifier: AGPL-3.0-or-later
// v0.2 uses its own line detector before CTC recognition. Rotating a whole
// multi-column speech bubble loses the Japanese column reading order.
import * as ort from 'onnxruntime-web/all';
import {downloadArtifactFromUrl} from './upstream/lib/utils.ts';
import {detectPpLines} from './detection.js';
let session,dict;
export async function recognizePpManga(source,boxes){
 const bitmap=await createImageBitmap(await(await fetch(source)).blob());
 try{
  const lines=await detectPpLines(bitmap);
  session??=await downloadArtifactFromUrl('https://huggingface.co/Kellenok/PP-OCRv6_manga/resolve/62375557b5b0a4b2bc8e05484a97c7ea1df7229e/rec/manga_rec_v0.2.onnx','ppocrv6-rec',{gpu:false});
  if(!dict){const r=await fetch(new URL('dicts/ppocrv6_dict.txt',location.href));if(!r.ok)throw Error('Не загружен словарь PP-OCRv6.');dict=['',...(await r.text()).trimEnd().split(/\r?\n/),' '];}
  const results=[];
  for(const box of boxes){
   const assigned=lines.filter(b=>{const x=(b.x1+b.x2)/2,y=(b.y1+b.y2)/2;return x>=box.x1&&x<=box.x2&&y>=box.y1&&y<=box.y2;}).sort((a,b)=>{const vertical=(a.y2-a.y1)>(a.x2-a.x1);return vertical?b.x1-a.x1:a.y1-b.y1;});
   let text='',score=0,count=0;
   for(const b of assigned){
    const x=Math.floor(b.x1),y=Math.floor(b.y1),w=Math.max(1,Math.ceil(b.x2)-x),h=Math.max(1,Math.ceil(b.y2)-y),vertical=h>w,natural=Math.round(48*(vertical?h/w:w/h)),tw=Math.max(16,Math.min(natural>2000?2400:640,natural));
    const crop=new OffscreenCanvas(vertical?h:w,vertical?w:h),c=crop.getContext('2d');
    if(vertical){c.translate(0,w);c.rotate(-Math.PI/2);}c.drawImage(bitmap,x,y,w,h,0,0,w,h);
    const resized=new OffscreenCanvas(tw,48),ctx=resized.getContext('2d');ctx.drawImage(crop,0,0,tw,48);const pixels=ctx.getImageData(0,0,tw,48).data,plane=tw*48,buf=new Float32Array(plane*3);
    for(let i=0;i<plane;i++)for(let ch=0;ch<3;ch++)buf[ch*plane+i]=pixels[i*4+ch]/127.5-1;
    const input=new ort.Tensor('float32',buf,[1,3,48,tw]);let output;
    try{output=await session.run({[session.inputNames[0]]:input});const tensor=output[session.outputNames[0]],values=await tensor.getData(),classes=tensor.dims.at(-1);if(classes!==dict.length)throw Error('Словарь PP-OCRv6 не соответствует модели.');
     let last=0;for(let i=0;i<values.length;i+=classes){let idx=0,max=-Infinity;for(let j=0;j<classes;j++)if(values[i+j]>max){max=values[i+j];idx=j;}if(idx&&idx!==last){text+=dict[idx];score+=max;count++;}last=idx;}
    }finally{input.dispose();if(output)Object.values(output).forEach(v=>v.dispose());}
   }
   const confidence=count?score/count:0;
   results.push({text,confidence,failed:!text||confidence<.55});
  }return {results};
 }finally{bitmap.close();}
}
