import {blockPackets,linkPageBlocks,packBlockSheets,unpackBlockTranslations} from './manga-blocks.js';

export const unresolvedRegions=page=>(page.regions||[]).filter(r=>!r.ru_translation?.trim()&&r.empty_reason!=='non_text');
export const needsEmptyReview=page=>!page.emptyReview?.attempted&&unresolvedRegions(page).length>0;

// A blank model answer is not proof that the detector found no readable text.
// Review all blank labels together, once per packet, on enlarged crop sheets.
// The original credential remains leased; callGoogle paces this extra request.
export async function reviewEmptyTranslations(c,pages,sources,options,{retry=false}={}){
 const targets=pages.filter(retry?p=>unresolvedRegions(p).length:needsEmptyReview),ids=new Set(targets.flatMap(p=>unresolvedRegions(p).map(r=>r.uid)));
 if(!ids.size)return pages;
 const review={attempted:true,ids:[...ids],recovered:[]};
 try{
  const selected=sources.map(p=>{
   const rows=unresolvedRegions(targets.find(target=>target.page===p.page)||{});
   const regions=p.inputMode==='vision'||retry
    ?rows.map(r=>({id:r.uid,bbox:r.text_bbox,layout_bbox:r.layout_bbox,bubble_bbox:r.bubble_bbox}))
    :p.regions.filter(r=>ids.has(r.id));
   return {...p,regions};
  }).filter(p=>p.regions.length);
  const groups=linkPageBlocks(selected,{direction:c.direction,webtoon:c.config.webtoon});
  // Upscale only the review image. Original coordinates/layout never change.
  for(const group of groups){group.scale=Math.max(1,Math.min(2,1200/Math.max(group.width,group.height)));group.width*=group.scale;group.height*=group.scale;}
  const sheets=packBlockSheets(groups);
  if(!sheets.length)throw Error('Нет координат пропущенных реплик.');
  c.controller.signal.throwIfAborted();
  const packed=await c.canvasTask({operation:'blocks-pack',channel:'prepare',sheets,pages:selected});
  const rows=new Map();review.usage=[];
  for(const packet of blockPackets(packed)){
   try{
    const answer=await c.callGoogle(packet,{...options,paced:false,gemmaProfile:'compat',allowMissing:true,reviewEmptyIds:packet.flatMap(s=>s.regions.map(r=>r.id))});
    for(const page of unpackBlockTranslations(answer.pages,packet,selected))for(const row of page.regions)rows.set(row.uid,row);
    review.usage.push(answer.usage);
   }catch(error){c.controller.signal.throwIfAborted();review.error=error.message;}
  }
  // Merge content only: scaled review-sheet geometry must never reach layout.
  for(const page of targets)page.regions=page.regions.map(region=>{
   const row=rows.get(region.uid);if(!ids.has(region.uid)||!row)return region;
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
