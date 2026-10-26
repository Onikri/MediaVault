// Quality defaults follow real vertical-manga and Korean-page measurements.
// Explicit user choices remain available for speed/accuracy comparisons.
export function resolveMangaOcr(language,selected){
 if(selected&&selected!=='auto')return selected;
 return language==='Japanese'?'manga-ocr':language==='Korean'?'ppocrv5-korean':'paddle';
}
