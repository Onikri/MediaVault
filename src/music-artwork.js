// YouTube's 4:3 thumbnails wrap a 16:9 frame in baked-in letterbox bands.
// Square album artwork and wide/max-resolution frames need no extra zoom.
export function musicArtworkCrop(url,width=0,height=0){
 let source;try{source=new URL(url);}catch{return 1;}
 if(source.hostname!=='i.ytimg.com')return 1;
 if(width>0&&height>0)return Math.abs(width/height-4/3)<.025?1.34:1;
 return /\/(?:hqdefault|sddefault|default|[0-3])\.(?:jpg|webp)$/i.test(source.pathname)?1.34:1;
}
