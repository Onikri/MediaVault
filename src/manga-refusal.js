// Google refuses a whole request when one image or line in it trips a safety
// filter (PROHIBITED_CONTENT on adult or violent pages). Split the refused
// request and retry on Google first: pages one by one, then native-resolution
// crops of a page's bubbles, then halves of those crops down to one bubble.
// Only bubbles Google still refuses are marked `refused`; the non-Google
// fallback model (manga-fallback.js) translates them afterwards.
import {isGoogleRefusal,DIRECT_FONTS} from './manga-direct-api.js';
import {blockPackets,linkPageBlocks,packBlockSheets,unpackBlockTranslations} from './manga-blocks.js';

// Extra Google requests one refused packet may spend on splitting. Each costs
// quota and at least the 4 s key pacing; past it the remaining bubbles go to
// the fallback model at once, so a fully explicit page stays in tens of seconds.
export const SPLIT_BUDGET=6;
export function refusalLedger(budget=SPLIT_BUDGET){return {budget,requests:0,refusals:0,reasons:[],usage:[]};}
const refusedRow=(uid,refusal)=>({uid,ru_translation:'',empty_reason:'refused',refused:refusal,source_text:'',font_style:DIRECT_FONTS[0],text_category:'dialogue'});
const groupMembers=packet=>packet.flatMap(sheet=>sheet.placements.map(p=>p.group.parts.map(part=>part.id)));
function note(ledger,error){ledger.refusals++;if(ledger.reasons.length<12)ledger.reasons.push(error.refusal);}

// Translate the listed bubbles as crop sheets. A refused packet is halved by
// bubble groups (webtoon seams stay joined) until a single group is refused.
export async function translateCrops(c,sources,ids,options,{review=false,tolerant=false,ledger=refusalLedger(),skipWhole=false}={}){
 const wanted=new Set(ids),rows=new Map(),refused=new Map();
 const selected=sources.map(p=>({...p,regions:p.regions.filter(r=>wanted.has(r.id))})).filter(p=>p.regions.length);
 if(!selected.length)return {rows,refused,ledger};
 const groups=linkPageBlocks(selected,{direction:c.direction,webtoon:c.config.webtoon});
 // Review crops are enlarged for reading; original coordinates never change.
 if(review)for(const group of groups){group.scale=Math.max(1,Math.min(2,1200/Math.max(group.width,group.height)));group.width*=group.scale;group.height*=group.scale;}
 const merge=part=>{for(const[id,row]of part.rows)rows.set(id,row);for(const[id,why]of part.refused)refused.set(id,why);};
 const split=async(members,error)=>{
  if(members.length===1||ledger.requests>=ledger.budget){for(const id of members.flat())refused.set(id,error.refusal);return;}
  const half=Math.ceil(members.length/2);
  for(const part of [members.slice(0,half),members.slice(half)])merge(await translateCrops(c,sources,part.flat(),options,{review,tolerant,ledger}));
 };
 // The caller already saw exactly this content refused: go straight to halves.
 if(skipWhole){await split(groups.map(g=>g.parts.map(p=>p.id)),{refusal:skipWhole});return {rows,refused,ledger};}
 const sheets=packBlockSheets(groups);
 if(!sheets.length)throw Error('Нет координат реплик для вырезок.');
 c.controller.signal.throwIfAborted();
 const packed=await c.canvasTask({operation:'blocks-pack',channel:'prepare',sheets,pages:selected});
 for(const packet of blockPackets(packed)){
  // Budget spent by earlier halves: hand the rest to the fallback unsent.
  if(ledger.requests>=ledger.budget&&ledger.refusals){for(const id of groupMembers(packet).flat())refused.set(id,ledger.reasons.at(-1));continue;}
  ledger.requests++;
  try{
   const answer=await c.callGoogle(packet,{...options,paced:false,gemmaProfile:'compat',allowMissing:true,...(review?{reviewEmptyIds:packet.flatMap(s=>s.regions.map(r=>r.id))}:{})});
   for(const page of unpackBlockTranslations(answer.pages,packet,selected))for(const row of page.regions)rows.set(row.uid,row);
   ledger.usage.push(answer.usage);
  }catch(error){
   c.controller.signal.throwIfAborted();
   if(!isGoogleRefusal(error)){if(tolerant){ledger.error=error.message;continue;}throw error;}
   note(ledger,error);await split(groupMembers(packet),error);
  }
 }
 return {rows,refused,ledger};
}

// c.callGoogle with refusal splitting for every input mode except `vision`
// (Google finds the regions itself there; nothing local to split). Returns the
// same shape as callGoogle, so callers merge and validate pages unchanged.
export async function callGoogleSplitting(c,packet,options,{sources=[],ledger=refusalLedger()}={}){
 try{return await c.callGoogle(packet,options);}
 catch(error){
  if(!isGoogleRefusal(error)||!packet.length||packet[0].inputMode==='vision')throw error;
  c.controller.signal.throwIfAborted();note(ledger,error);
  const answer={pages:[],usage:[],diagnostics:error.diagnostics,refusal:ledger};
  if(packet[0].inputMode==='blocks'){
   // Sheets: halve the refused bubble groups, then answer per sheet label so
   // unpackBlockTranslations restores the original page geometry.
   const pages=sources.filter(s=>packet.some(sheet=>sheet.placements.some(p=>p.group.parts.some(part=>part.page===s.page))));
   const members=groupMembers(packet),{rows,refused}=await translateCrops(c,pages,members.flat(),options,{ledger,skipWhole:error.refusal});
   answer.pages=packet.map(sheet=>({page:sheet.page,width:sheet.width,height:sheet.height,regions:sheet.regions.map(r=>({...(rows.get(r.id)||refusedRow(r.id,refused.get(r.id)||error.refusal)),uid:r.id,text_bbox:r.bbox,layout_bbox:r.bbox}))}));
   answer.usage=ledger.usage;return answer;
  }
  if(packet.length>1){
   for(const page of packet){const part=await callGoogleSplitting(c,[page],{...options,paced:false},{sources,ledger});answer.pages.push(...part.pages);answer.usage.push(...[].concat(part.usage??[]));}
   return answer;
  }
  // One full annotated page: retry its bubbles as crops without the artwork.
  const page=packet[0],source=sources.find(s=>s.page===page.page);
  if(!source?.blob)throw error;
  const ids=page.regions.map(r=>r.id),{rows,refused}=await translateCrops(c,[source],ids,options,{ledger});
  answer.pages.push({page:page.page,width:page.width,height:page.height,regions:page.regions.map(r=>rows.get(r.id)||{...refusedRow(r.id,refused.get(r.id)||error.refusal),text_bbox:r.bbox,layout_bbox:r.layout_bbox||r.bbox}),timings:{detectionMs:page.detectionMs,ocrMs:0},refusal:ledger});
  answer.usage=ledger.usage;return answer;
 }
}
