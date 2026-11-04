// Only background footage is cropped. The actual player retains the whole frame.
export function letterboxScale(pixels,width,height){
 const blackRow=y=>{let dark=0;for(let x=0;x<width;x++){const p=(y*width+x)*4;if(Math.max(pixels[p],pixels[p+1],pixels[p+2])<22)dark++;}return dark/width>.96;};
 let top=0,bottom=0;
 while(top<height*.2&&blackRow(top))top++;
 while(bottom<height*.2&&blackRow(height-bottom-1))bottom++;
 if(Math.min(top,bottom)<1||Math.abs(top-bottom)>1||top+bottom>=height*.38)return 1;
 let bright=0,total=0;
 for(let y=Math.ceil(height*.3);y<height*.7;y++)for(let x=0;x<width;x++){total++;const p=(y*width+x)*4;if(Math.max(pixels[p],pixels[p+1],pixels[p+2])>55)bright++;}
 return bright/total>.15?Math.min(1.32,height/(height-2*Math.min(top,bottom))):1;
}
const inspected=new WeakSet();
export function cropBackgroundBars(video){
 if(inspected.has(video))return;
 inspected.add(video);let previous=1,attempt=0;
 const sample=()=>{
  if(!video.isConnected||video.paused)return;
  try{
   const canvas=document.createElement('canvas');canvas.width=64;canvas.height=36;
   const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0,64,36);
   const scale=letterboxScale(ctx.getImageData(0,0,64,36).data,64,36);
   if(scale>1.04&&Math.abs(scale-previous)<.01){video.style.setProperty('--background-crop',String(scale));return;}
   previous=scale;if(++attempt<3)setTimeout(sample,450);
  }catch{/* Cross-origin footage remains object-fit:cover without pixel access. */}
 };
 sample();
}
