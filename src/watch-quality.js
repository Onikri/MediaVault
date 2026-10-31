// Quality metadata only: never persist expiring CDN URLs or infer missing heights.
export function qualityHeights(rows){return [...new Set(rows.flatMap(r=>r.qualities||[]).map(Number).filter(n=>Number.isInteger(n)&&n>0&&n<=8640))].sort((a,b)=>b-a);}
export function bestQualityRow(rows,{voiceId,quality='best',anyVoice=false,failed=new Set()}={}){
 return rows.filter(r=>(anyVoice||r.voiceId===voiceId)&&!failed.has(r.variant.id)&&(quality==='best'||r.qualities.includes(Number(quality))))
  .sort((a,b)=>(b.qualities[0]||0)-(a.qualities[0]||0)||Number(b.voiceId===voiceId)-Number(a.voiceId===voiceId))[0];
}
export function contiguousBufferEnd(ranges,time){for(let i=0;i<ranges.length;i++)if(ranges.start(i)<=time+.1&&ranges.end(i)>=time)return ranges.end(i);return time;}
export function streamBufferPolicy({preview=false,audioOnly=false,saveData=false,memory=8}={}){
 const small=memory<=4;
 return {maxBufferLength:preview?8:saveData?20:small?60:120,maxMaxBufferLength:preview?12:saveData?30:small?90:180,
  maxBufferSize:(preview?8:saveData?20:small?60:120)*1000*1000,backBufferLength:preview?0:saveData?10:30,
  abrBandWidthFactor:.9,abrBandWidthUpFactor:.65,abrMaxWithRealBitrate:true,maxStarvationDelay:2,maxLoadingDelay:4,
  startFragPrefetch:!preview,capLevelToPlayerSize:false,...(audioOnly?{maxBufferSize:40*1000*1000}:{} )};
}
