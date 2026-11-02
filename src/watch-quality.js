// Quality metadata only: never persist expiring CDN URLs or infer missing heights.
export function qualityHeights(rows){return [...new Set(rows.flatMap(r=>r.qualities||[]).map(Number).filter(n=>Number.isInteger(n)&&n>0&&n<=8640))].sort((a,b)=>b-a);}
export function bestQualityRow(rows,{voiceId,quality='best',anyVoice=false,failed=new Set()}={}){
 return rows.filter(r=>(anyVoice||r.voiceId===voiceId)&&!failed.has(r.variant.id)&&(quality==='best'||r.qualities.includes(Number(quality))))
  .sort((a,b)=>(b.qualities[0]||0)-(a.qualities[0]||0)||Number(b.voiceId===voiceId)-Number(a.voiceId===voiceId))[0];
}
export function contiguousBufferEnd(ranges,time){for(let i=0;i<ranges.length;i++)if(ranges.start(i)<=time+.1&&ranges.end(i)>=time)return ranges.end(i);return time;}
export function streamBufferPolicy({preview=false,audioOnly=false,saveData=false,memory=8}={}){
 const small=memory<=4;
 return {maxBufferLength:preview?6:saveData?15:small?40:75,maxMaxBufferLength:preview?12:saveData?20:small?60:90,
  maxBufferSize:(preview?4:saveData?12:small?32:64)*1024*1024,backBufferLength:preview?0:saveData?5:small?8:15,
  abrBandWidthFactor:.9,abrBandWidthUpFactor:.65,abrMaxWithRealBitrate:true,maxStarvationDelay:2,maxLoadingDelay:4,
  startFragPrefetch:!preview,capLevelToPlayerSize:false,...(audioOnly?{maxBufferSize:40*1000*1000}:{} )};
}
export function bitrateBufferPolicy(policy,bitrate){if(!(bitrate>0))return policy;const seconds=Math.max(6,policy.maxBufferSize*8/bitrate);return {...policy,maxBufferLength:Math.min(policy.maxBufferLength,seconds),maxMaxBufferLength:Math.min(policy.maxMaxBufferLength,seconds)};}
export function initialStreamLevel(levels,{preview=false,audioOnly=false,saveData=false,downlink,memory=8}={}){
 if(preview||audioOnly||saveData)return 0;
 const estimate=(Number(downlink)>0?Number(downlink):memory<=4?3:6)*1000000*.8;
 const candidates=levels.map((l,index)=>({index,bitrate:Number(l.bitrate)||Infinity})).filter(l=>l.bitrate<=estimate).sort((a,b)=>b.bitrate-a.bitrate);
 return candidates[0]?.index??0;
}
