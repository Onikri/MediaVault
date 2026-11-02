export function cursorMusicTime(clientX,rect,duration){
 if(!rect||!Number.isFinite(duration)||duration<=0||rect.width<=0)return 0;
 return Math.max(0,Math.min(duration,(clientX-rect.left)/rect.width*duration));
}
