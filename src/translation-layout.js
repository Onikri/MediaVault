export function translationFont(region,size){
 const width=Math.max(1,Number(region.w)*Number(size?.width||0)-8),height=Math.max(1,Number(region.h)*Number(size?.height||0)-6);
 const length=Math.max(1,Array.from(String(region.text||'')).length);
 const longest=Math.max(1,...String(region.text||'').split(/\s+/).map(word=>Array.from(word).length));
 return Math.max(9,Math.min(18,Math.floor(Math.min(Math.sqrt(width*height/(length*.75)),width/(longest*.62)))));
}
