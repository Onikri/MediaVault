import {translateCrops,refusalLedger} from './manga-refusal.js';

export const unresolvedRegions=page=>(page.regions||[]).filter(r=>!r.ru_translation?.trim()&&r.empty_reason!=='non_text');
// Bubbles Google refused were already split down to single crops; asking
// Google again only spends quota. They wait for the fallback model instead.
const reviewable=page=>unresolvedRegions(page).filter(r=>!r.refused);
export const needsEmptyReview=page=>!page.emptyReview?.attempted&&reviewable(page).length>0;

// A blank model answer is not proof that the detector found no readable text.
// Review all blank labels together, once per packet, on enlarged crop sheets.
// The original credential remains leased; callGoogle paces this extra request.
// A refused review sheet is halved like any other refused request.
export async function reviewEmptyTranslations(c,pages,sources,options,{retry=false}={}){
 const targets=pages.filter(retry?p=>reviewable(p).length:needsEmptyReview),ids=new Set(targets.flatMap(p=>reviewable(p).map(r=>r.uid)));
 if(!ids.size)return pages;
 const review={attempted:true,ids:[...ids],recovered:[]};
 try{
  const selected=sources.map(p=>{
   const rows=reviewable(targets.find(target=>target.page===p.page)||{});
   const regions=p.inputMode==='vision'||retry
    ?rows.map(r=>({id:r.uid,bbox:r.text_bbox,layout_bbox:r.layout_bbox,bubble_bbox:r.bubble_bbox}))
    :p.regions.filter(r=>ids.has(r.id));
   return {...p,regions};
  }).filter(p=>p.regions.length);
  if(!selected.length)throw Error('Нет координат пропущенных реплик.');
  const ledger=refusalLedger(),{rows,refused}=await translateCrops(c,selected,[...ids],options,{review:true,tolerant:true,ledger});
  review.usage=ledger.usage;if(ledger.error)review.error=ledger.error;if(ledger.refusals)review.refusals=ledger.refusals;
  // Merge content only: scaled review-sheet geometry must never reach layout.
  for(const page of targets)page.regions=page.regions.map(region=>{
   if(!ids.has(region.uid))return region;
   if(refused.has(region.uid))return {...region,ru_translation:'',empty_reason:'refused',refused:refused.get(region.uid)};
   const row=rows.get(region.uid);if(!row)return region;
   if(row.ru_translation?.trim())review.recovered.push(region.uid);
   return {...region,ru_translation:row.ru_translation,font_style:row.font_style,text_category:row.text_category,empty_reason:row.empty_reason};
  });
 }catch(error){
  c.controller.signal.throwIfAborted();
  // Preserve translations that already succeeded, including on a quota error.
  review.error=error.message;
 }
 for(const page of targets)page.emptyReview={...review,ids:review.ids.filter(id=>page.regions.some(r=>r.uid===id)),recovered:review.recovered.filter(id=>page.regions.some(r=>r.uid===id))};
 return pages;
}
