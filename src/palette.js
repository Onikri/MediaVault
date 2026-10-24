const luminance=rgb=>rgb.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
export const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
export function scenePalette(pixels){
  const bins=new Map();
  for(let i=0;i<pixels.length;i+=16){
    const rgb=[pixels[i],pixels[i+1],pixels[i+2]],max=Math.max(...rgb),min=Math.min(...rgb),light=luminance(rgb);
    if(light<.025||light>.8)continue;
    const key=rgb.map(v=>Math.floor(v/32)).join(','),weight=(max-min)/255+.15;
    const bin=bins.get(key)||{sum:[0,0,0],weight:0};bin.weight+=weight;rgb.forEach((v,j)=>bin.sum[j]+=v*weight);bins.set(key,bin);
  }
  const best=[...bins.values()].sort((a,b)=>b.weight-a.weight)[0];
  const base=best?best.sum.map(v=>Math.round(v/best.weight)):[216,153,113];
  let accent=[...base];
  for(let i=0;i<12&&contrast(accent,[23,26,32])<5;i++)accent=accent.map(v=>Math.round(v+(255-v)*.13));
  return {base:base.join(' '),accent:accent.join(' '),accentCSS:'rgb('+accent.join(' ')+')'};
}
