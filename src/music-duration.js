// Metadata/search duration may be available before an audio capability exists.
export function knownMusicDuration(track={},mediaDuration=0,metadata={},record={}){
 const values=[mediaDuration,Number(metadata?.durationMs)/1000,record?.duration,track?.duration];
 for(const value of values){const parts=typeof value==='string'?value.split(':').map(Number):null;const seconds=parts?.length>1&&parts.length<=3&&parts.every(Number.isFinite)?parts.reduce((a,n)=>a*60+n,0):Number(value);if(Number.isFinite(seconds)&&seconds>0&&seconds<=7200)return seconds;}
 return 0;
}
