// A deterministic luminance/edge/centre prior, not neural depth estimation.
// The complete original remains the far layer; the near layer only adds subtle relief.
export function reliefLayer(canvas){
 const w=Math.min(320,canvas.width),h=Math.round(w*canvas.height/canvas.width),mask=document.createElement('canvas');mask.width=w;mask.height=h;const ctx=mask.getContext('2d');ctx.drawImage(canvas,0,0,w,h);const raw=ctx.getImageData(0,0,w,h),p=raw.data;
 const luma=(x,y)=>{const i=(Math.max(0,Math.min(h-1,y))*w+Math.max(0,Math.min(w-1,x)))*4;return (p[i]*.2126+p[i+1]*.7152+p[i+2]*.0722)/255;};
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){const centre=Math.max(0,1-Math.hypot((x/w-.5)*1.5,(y/h-.52)*1.1)),edge=Math.min(1,Math.abs(luma(x-2,y)-luma(x+2,y))*2+Math.abs(luma(x,y-2)-luma(x,y+2))*2),score=centre*.65+edge*.22+luma(x,y)*.13,t=Math.max(0,Math.min(1,(score-.32)/.48));p[(y*w+x)*4+3]=Math.round(t*t*(3-2*t)*215);}
 ctx.putImageData(raw,0,0);const layer=document.createElement('canvas');layer.width=canvas.width;layer.height=canvas.height;const out=layer.getContext('2d');out.drawImage(canvas,0,0);out.globalCompositeOperation='destination-in';out.drawImage(mask,0,0,layer.width,layer.height);return layer.toDataURL('image/png');
}
