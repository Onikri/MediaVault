// Connection point for a second translator that handles speech bubbles Google
// refused (for example PROHIBITED_CONTENT) or left blank after its own review.
//
// A provider is registered once at start-up:
//   setBubbleFallback(async ({pages,sources,language,direction,signal,onStatus})=>pages)
// pages:   reader JSON pages {page, width, height, regions:[{uid,text_bbox,layout_bbox,ru_translation,empty_reason,...}]}
//          The provider fills ru_translation only for regions listed in page.unresolved
//          and may mark them with region.fallback={model}. Geometry must not change.
// sources: [{page, width, height, blob}] original page images (same order as pages).
// Returning pages (or nothing, after mutating them) is enough: DirectChapter
// caches the result, re-renders the page and the save dialog drops it from the
// list of untranslated pages.
let provider=null;
export function setBubbleFallback(fn){provider=typeof fn==='function'?fn:null;return ()=>{if(provider===fn)provider=null;};}
export function bubbleFallback(){return provider;}
