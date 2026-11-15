import {comicLayouts,verticalLettering} from './manga-layout.js';
import {teleaInpaint} from '../lmt/upstream/lib/inpaint/telea.ts';
import {loadMangaFont,loadPrivateFace,loadPrivateById,MANGA_FONTS} from '../reader-fonts/catalog.js';
import {normalizeText} from '../lmt/typeset/normalize.js';
import {makeRegion,ellipseRegion,erodeRegion} from '../lmt/typeset/shape.js';
import {fitPage} from '../lmt/typeset/fit.js';
import {measurer,drawLayout} from '../lmt/typeset/draw.js';
import {periodicFill} from '../lmt/upstream/lib/inpaint/tone.ts';
import {fitComicText,styleFont,comicInkColor} from './manga-typeset.js';
import {prepareInkPatch,preparePageInk,compositeInkPatch,dilateInk} from './manga-cleaning.js';
export const READER_RENDER_VERSION=15;
export const READER_TYPESETTER='shaped-cyrillic-ru-v7';
// The face of ordinary text when the listener leaves the choice to the reader.
export const MAIN_FONT='neucha';
// One main typeface carries speech, thoughts (italic) and shouts; only sound
// effects, small side chatter and notes on objects get a situational face.
const SITUATIONAL=new Set(['sfx','chatter','note']);
// The voice of a line picks its face, as a letterer does: a scream, a furious
// line, a faint one and a plain one are not set in the same type. The voice
// comes from what the text is, from the weight the model saw in the source
// lettering and from the line's own punctuation.
export function voiceOf(region,role,text=''){
 const style=region.font_style||'',value=String(text).trim();
 if(role==='sfx')return 'sfx';
 if(role==='note')return /handwritten/.test(style)?'script':'sign';
 if(role==='chatter')return 'weak';
 if(region.text_category==='system_ui')return 'system';
 if(role==='narration')return 'narration';
 const screams=/!{2,}["»”]?$/.test(value),mixed=/(?:\?!|!\?)["»”]?$/.test(value);
 if(style==='bold_scream')return screams?'shout':mixed?'angry':'strong';
 if(role==='thought')return 'speech';
 if(screams)return 'strong';
 if(style==='handwritten_narrow'||style==='handwritten_soft')return 'weak';
 if(style==='handwritten_sloppy')return 'script';
 return 'speech';
}
// Open faces used when the owner supplied none for a voice: [font, weight].
// The classic narrow hand-lettered face of printed manga for lines, thoughts
// and captions; a raised voice is the same face heavier (EMBOLDEN, in em).
const OPEN_FACE={speech:[MAIN_FONT,400],strong:[MAIN_FONT,400],shout:['balsamiq-sans',700],angry:['balsamiq-sans',700],weak:['pangolin',400],script:['caveat',400],
 narration:[MAIN_FONT,400],sign:['pt-serif',400],sfx:['ruslan-display',400],eerie:['ruslan-display',400],system:['press-start',400]};
const EMBOLDEN={speech:.035,narration:.035,strong:.075};
const CAPS_VOICES=new Set(['speech','strong','shout','angry','narration','sign']);
const LOUDER={shout:1.9,angry:1.7};
const ROLE={sfx:'sfx',sign:'note',whisper_aside:'chatter',narration:'narration',thought:'thought',system_ui:'narration'};
// The role comes from what the text is, never from the style the model guessed
// for its glyphs: that guess is noisy and gave ordinary lines stray faces.
const roleOf=region=>ROLE[region.text_category]||'speech';
// Usable interior of a caption: the flood-filled paper rows when known, an
// ellipse for a detector balloon, the source box otherwise. The text is
// centred on this figure as drawn; a balloon cut by the page edge stays cut.
function letteringShape(region,box){
 const b={x1:box[0],y1:box[1],x2:box[2],y2:box[3]},s=region.bubble_shape,w=b.x2-b.x1,h=b.y2-b.y1;
 if(s){
  const y0=Math.floor(b.y1),n=Math.max(1,Math.ceil(b.y2)-y0),left=new Float32Array(n),right=new Float32Array(n);let area=0;
  for(let i=0;i<n;i++){const r=y0+i-s.top;if(r<0||r>=s.height||s.rows[r*2+1]<s.rows[r*2])continue;const l=Math.max(b.x1,s.left+s.rows[r*2]),e=Math.min(b.x2,s.left+s.rows[r*2+1]+1);if(e>l){left[i]=l;right[i]=e;area+=e-l;}}
  const raw=makeRegion({y0,left,right,kind:'bubble'}),shape=erodeRegion(raw,Math.max(3,.055*Math.min(raw.width,raw.height)));
  if(shape.width>0&&shape.height>0){shape.rectangularity=area/Math.max(1,w*h);return shape;}
 }
 if(region.bubble_bbox)return ellipseRegion(b,Math.max(3,.06*Math.min(w,h)),'bubble');
 return ellipseRegion({x1:b.x1-w*.075,y1:b.y1-h*.075,x2:b.x2+w*.075,y2:b.y2+h*.075},0,'box');
}
function overlap(a,b){const area=(a[2]-a[0])*(a[3]-a[1]),other=(b[2]-b[0])*(b[3]-b[1]),shared=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));return shared/Math.max(1,area+other-shared);}
function maskRuns(patch,pageWidth,mask=patch.mask){const runs=[];for(let y=0;y<patch.height;y++){let x=0;while(x<patch.width){while(x<patch.width&&!mask[y*patch.width+x])x++;const start=x;while(x<patch.width&&mask[y*patch.width+x])x++;if(x>start)runs.push((patch.top+y)*pageWidth+patch.left+start,(patch.top+y)*pageWidth+patch.left+x);}}return runs;}
export async function renderComicPage({blob,page,font='auto',mode='hybrid',lama,cache=false,status=()=>{},moebiusStrategy='page',captureDebug=false,cleanOnly=false,preparedClean,caps=true,voiceFonts={}}){
 const start=performance.now(),bitmap=await createImageBitmap(blob);
 try{
  if(bitmap.width!==page.width||bitmap.height!==page.height||bitmap.width*bitmap.height>24_000_000)throw Error('Размер исходной страницы изменился.');
  const canvas=new OffscreenCanvas(bitmap.width,bitmap.height),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,0);
  const original=ctx.getImageData(0,0,canvas.width,canvas.height),working=new ImageData(original.data.slice(),original.width,original.height),plans=[],records=[],warnings=[],methods=new Set();let inpaintMs=0,typesetMs=0;
  const normalize=text=>String(text).normalize('NFC').replace(/[\u200b\u00ad]/g,'').replace(/\s+/g,' ').trim();
  const unresolved=page.regions.filter(r=>!r.ru_translation?.trim()&&r.empty_reason!=='non_text');
  if(!cleanOnly&&unresolved.length)warnings.push('Нет перевода для '+unresolved.length+' областей ('+unresolved.map(r=>r.uid).join(', ')+'). Их оригинал сохранён; повтори перевод страницы.'+(page.emptyReview?.error?' Проверка пропусков: '+page.emptyReview.error:''));
  // Plan and measure every caption before changing any pixel.
  for(const sourceRegion of cleanOnly?page.regions:comicLayouts(original,page.regions)){
   const region={...sourceRegion};
   const text=normalize(region.ru_translation||'');if(!cleanOnly&&!text)continue;
   let box=region.layout_bbox||region.bubble_bbox||region.text_bbox;
   const valid=b=>Array.isArray(b)&&b.length===4&&b.every(Number.isFinite)&&b[0]>=0&&b[1]>=0&&b[2]<=page.width&&b[3]<=page.height&&b[2]>b[0]&&b[3]>b[1];
   if(!valid(box)||!valid(region.text_bbox)){records.push({uid:region.uid,method:'declined',reason:'Некорректная область вёрстки'});continue;}
   if(cleanOnly){plans.push({region,box});continue;}
   // One face for lines, thoughts and the author's text (a shout is the same
   // face in bold); the model's style picks a face only for sound effects, side
   // remarks, signs and system windows.
   // The listener may pick a face for each voice in the settings.
   const role=roleOf(region),voice=voiceOf(region,role,text),slot=role==='thought'?'thought':voice,chosen=font==='auto'?voiceFonts?.[slot]||voiceFonts?.[voice]:null;
   const open=chosen&&MANGA_FONTS.some(f=>f.id===chosen)?[chosen,OPEN_FACE[voice]?.[1]||400]:OPEN_FACE[voice]||OPEN_FACE.speech;
   const idFont=font==='auto'?open[0]:font,weight=font==='auto'?open[1]:region.font_style==='bold_scream'?700:400;let family;
   try{family=idFont==='serif'?'Georgia, serif':idFont==='mono'?'monospace':await loadMangaFont(idFont);}catch{family='system-ui';warnings.push('Шрифт не загрузился: использован системный шрифт.');}
   const flow=region.flow;
   if(flow&&(![flow.width,flow.height,flow.offsetY].every(Number.isFinite)||flow.width<=0||flow.height<=0||flow.offsetY<0||flow.offsetY+box[3]-box[1]>flow.height+1)){records.push({uid:region.uid,method:'declined',reason:'Некорректная связанная область'});continue;}
   const vertical=!flow&&verticalLettering(box,page.height,region.text_category,!!region.bubble_bbox),fitBox=flow?[0,0,flow.width,flow.height]:vertical?[0,0,box[3]-box[1],box[2]-box[0]]:box;
   if(!flow&&!vertical){
    // Shaped composition; linked webtoon cells and vertical captions keep the cell fitter below.
    // The owner's own typefaces come first: one named for dialogue replaces the main face.
    const picked=chosen?.startsWith('private:')?await loadPrivateById(chosen,{fallback:family}).catch(()=>null):null;
    const own=font!=='auto'||chosen&&!picked?null:picked||(role==='thought'?await loadPrivateFace('thought',{fallback:family}).catch(()=>null):null)||await loadPrivateFace(voice,{fallback:family}).catch(()=>null);
    // A face drawn italic needs no slant of its own.
    const face=own?{...own,italic:role==='thought'&&own.voice!=='thought'}:{id:idFont,stack:family,weight,italic:role==='thought',upper:false,embolden:font==='auto'?EMBOLDEN[voice]||0:0};
    plans.push({region,box,idFont:face.id,family,weight,role,voice,face,shape:letteringShape(region,box),text:normalizeText(text,{caps:voice==='sfx'||voice==='shout'||caps&&CAPS_VOICES.has(voice)&&(!own||own.upper)})});continue;
   }
   const fit=fitComicText(text,fitBox,(value,size)=>{ctx.font=`${weight} ${size}px ${family}`;return ctx.measureText(value).width;},{oval:!flow&&!!region.bubble_bbox,max:Math.min(96,Math.max(42,Math.round(Math.sqrt((box[2]-box[0])*(box[3]-box[1]))/3)))});
   if(!fit.fits){records.push({uid:region.uid,method:'declined',reason:'Перевод не помещается; исходные буквы сохранены'});continue;}
   plans.push({region,text,box,idFont,family,weight,fit,vertical});
  }
  // One average size for the page; a caption is smaller only when it does not
  // fit, and a word is hyphenated before the size is reduced.
  const shaped=plans.filter(p=>p.shape);let baseSize;
  if(shaped.length){
   const set=fitPage(shaped.map((p,index)=>({index,text:p.text,region:p.shape,box:{x1:p.box[0],y1:p.box[1],x2:p.box[2],y2:p.box[3]},role:p.role,loud:LOUDER[p.voice]||1,measure:measurer(ctx,p.face)})),{pageWidth:page.width});
   baseSize=Math.round(set.base*10)/10;
   shaped.forEach((p,i)=>{p.layout=set.layouts[i];});
   for(const p of shaped)if(p.layout.overflow){records.push({uid:p.region.uid,method:'declined',reason:'Перевод не помещается; исходные буквы сохранены'});plans.splice(plans.indexOf(p),1);}
  }
  // Conflicting duplicate boxes must not be painted over one another.
  const conflicts=new Set();for(let i=0;i<plans.length;i++)for(let j=i+1;j<plans.length;j++)if(overlap(plans[i].region.text_bbox,plans[j].region.text_bbox)>.85){conflicts.add(i);conflicts.add(j);}
  // smart: the small model gets at most MODEL_BUDGET ms per page, so a busy page
  // is never held for minutes; regions after it are cleaned by the fast method.
  const MODEL_BUDGET=7000,modelStart=()=>performance.now();let modelMs=0;
  let lamaUnavailable=null,modelCalls=0,pageExecution,cleanupMask=captureDebug?new Uint8Array(original.width*original.height):null;
  if(mode==='moebius'&&moebiusStrategy==='page'&&!preparedClean){
   const t=performance.now(),eligible=[];
   for(const[i,plan]of plans.entries())if(conflicts.has(i))records.push({uid:plan.region.uid,method:'declined',reason:'Пересекающиеся текстовые области'});else eligible.push(plan);
   const merged=preparePageInk(original,eligible.map(p=>p.region),{model:'moebius'}),safe=[];
   if(cleanupMask)cleanupMask.set(merged.mask);
   for(const{region,patch}of merged.patches){const plan=eligible.find(p=>p.region===region);if(patch.declined)records.push({uid:region.uid,method:'declined',reason:patch.declined});else{plan.background=patch.background;safe.push(plan);}}
   if(safe.length&&merged.maskedPixels){
    status({phase:'cleaning',message:'Moebius · вся страница, общая маска · один проход',cleanedRegions:0,completedRegions:0,totalRegions:safe.length});
    try{
     if(!lama)throw Error('Moebius недоступен в этом обработчике');
     modelCalls++;pageExecution=await lama(working,merged.mask,message=>status({phase:'cleaning',message}));
     // Enforce the native mask at this boundary, regardless of provider output.
     for(let n=0;n<merged.mask.length;n++)if(!merged.mask[n])working.data.set(original.data.subarray(n*4,n*4+4),n*4);
     methods.add('moebius');for(const plan of safe){plan.painted=true;const patch=merged.patches.find(p=>p.region===plan.region).patch;if(cleanOnly)plan.runs=maskRuns(patch,original.width);records.push({uid:plan.region.uid,method:'moebius',execution:pageExecution,painted:true,sharedPagePass:true,maskKind:patch.maskKind,margin:patch.margin});}
    }catch(error){lamaUnavailable=error.message;working.data.set(original.data);for(const plan of safe)records.push({uid:plan.region.uid,method:'declined',reason:'Moebius: '+error.message});}
   }
   inpaintMs+=performance.now()-t;
  }
  let preparedPixels;
  if(preparedClean?.cleanedImage){const decoded=await createImageBitmap(new Blob([preparedClean.cleanedImage],{type:'image/png'}));try{if(decoded.width!==original.width||decoded.height!==original.height)throw Error('Размер фона изменился');const c=new OffscreenCanvas(original.width,original.height),cx=c.getContext('2d');cx.drawImage(decoded,0,0);preparedPixels=cx.getImageData(0,0,c.width,c.height).data;}finally{decoded.close();}}
  for(const[i,plan]of (mode==='moebius'&&moebiusStrategy==='page'&&!preparedClean?[]:plans).entries()){
   const region=plan.region;if(conflicts.has(i)){records.push({uid:region.uid,method:'declined',reason:'Пересекающиеся текстовые области'});continue;}
   const ready=preparedPixels&&preparedClean.regions.find(r=>r.uid===region.uid&&JSON.stringify(r.box)===JSON.stringify(region.text_bbox));
   if(ready){
    if(ready.painted){for(let n=0;n<ready.runs.length;n+=2){const a=ready.runs[n],b=ready.runs[n+1];working.data.set(preparedPixels.subarray(a*4,b*4),a*4);}if(cleanupMask){const runs=ready.inputRuns||ready.runs;for(let n=0;n<runs.length;n+=2)cleanupMask.fill(1,runs[n],runs[n+1]);}plan.painted=true;methods.add(ready.method);}
    records.push({...ready,prepared:true});continue;
   }
   status({phase:'cleaning',message:'Очистка областей · '+(i+1)+' / '+plans.length,cleanedRegions:records.filter(r=>r.painted).length,completedRegions:records.filter(r=>r.painted).length,totalRegions:plans.length});
   // smart: the letter mask of the fast mode; paper is filled at once and only
   // lettering that lies on the drawing goes to the small inpainting model.
   const smart=mode==='smart',t=performance.now();let patch=prepareInkPatch(original,region.text_bbox,{category:region.text_category,neural:mode!=='fast'&&!smart,model:mode,...(smart?{rescue:true,contextPad:64}:{})});
   // Lettering the letter search could not separate is still not left in the
   // original: the model gets the contrast mask of the glyphs in the box.
   if(patch.declined&&smart&&lama&&!lamaUnavailable&&modelMs<MODEL_BUDGET){const glyphs=prepareInkPatch(original,region.text_bbox,{category:region.text_category,neural:true,model:'migan'});if(!glyphs.declined)patch={...glyphs,wide:glyphs.mask,maskKind:'glyph-contrast'};}
   if(patch.declined){records.push({uid:region.uid,method:'declined',reason:patch.declined});continue;}
   if(cleanupMask)for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(patch.mask[y*patch.width+x])cleanupMask[(patch.top+y)*original.width+patch.left+x]=1;
   const image=new ImageData(patch.data.slice(),patch.width,patch.height);let method,execution,write=patch.mask;
   try{
    if(mode==='quality'||mode==='moebius'||mode==='migan'||mode==='hybrid'&&!patch.flat){
     if(lamaUnavailable)throw Error(lamaUnavailable);if(!lama)throw Error('LaMa недоступна в этом обработчике');
     try{modelCalls++;execution=await lama(image,patch.mask,message=>status({phase:'cleaning',message}));}catch(error){lamaUnavailable=error.message;throw error;}
     method=mode==='moebius'?'moebius':mode==='migan'?'migan':'lama';write=mode==='quality'||mode==='hybrid'?dilateInk(patch.mask,patch.width,patch.height,2):patch.mask;
    }else if(smart&&patch.wide&&lama&&!lamaUnavailable&&modelMs<MODEL_BUDGET&&await(async()=>{
     // Outlined lettering over the drawing: the model repaints letters and outline alike.
     const began=modelStart();try{modelCalls++;execution=await lama(image,patch.wide,message=>status({phase:'cleaning',message}));method='migan';write=patch.wide;modelMs+=modelStart()-began;return true;}
     catch(error){lamaUnavailable=error.message;image.data.set(patch.data);return false;}
    })()){
    }else if(patch.flat){
     for(let n=0;n<patch.mask.length;n++)if(patch.mask[n])for(let c=0;c<3;c++)image.data[n*4+c]=patch.background[c];method='adaptive-glyph-fill';
    }else{
     // Telea only receives a bounded mask with plenty of known context.
     if(patch.coverage>.6)throw Error('Недостаточно фона для Telea');
     // The model repaints a slightly wider band than the letters, so the grey
     // fringe of the old lettering does not survive as a ghost.
     if(smart&&lama&&!lamaUnavailable&&modelMs<MODEL_BUDGET)try{const began=modelStart(),wide=dilateInk(patch.mask,patch.width,patch.height,Math.max(1,Math.min(4,Math.round((patch.stroke||3)*.5))));modelCalls++;execution=await lama(image,wide,message=>status({phase:'cleaning',message}));method='migan';write=wide;modelMs+=modelStart()-began;}catch(error){lamaUnavailable=error.message;image.data.set(patch.data);write=patch.mask;}
     if(method!=='migan'){teleaInpaint(image,periodicFill(image,patch.mask).remaining,3);method='telea';}
    }
    compositeInkPatch(working,patch,image.data,write);plan.painted=true;if(cleanOnly){plan.runs=maskRuns(patch,original.width,write);if(write!==patch.mask)plan.inputRuns=maskRuns(patch,original.width,patch.mask);}plan.background=patch.background;methods.add(method);records.push({uid:region.uid,method,execution,painted:true,maskKind:patch.maskKind||'glyphs',coverage:patch.coverage,ms:performance.now()-t});
   }catch(error){records.push({uid:region.uid,method:'declined',reason:'Не удалось очистить область: '+error.message,ms:performance.now()-t});}
   inpaintMs+=performance.now()-t;
  }
  ctx.putImageData(working,0,0);
  if(cleanOnly)return {cleanedImage:await(await canvas.convertToBlob({type:'image/png'})).arrayBuffer(),width:page.width,height:page.height,mode,version:READER_RENDER_VERSION,inpaint:{modelCalls,execution:pageExecution,methods:[...methods]},regions:plans.map(p=>({...records.find(r=>r.uid===p.region.uid),uid:p.region.uid,box:p.region.text_bbox,painted:!!p.painted,runs:p.runs||[],...(p.inputRuns?{inputRuns:p.inputRuns}:{})})),timings:{inpaintMs}};
  let debug;
  if(captureDebug){
   // Background cleanup covers every detected label, independently of JSON.
   // Show that actual model input, not only the subset pasted into the final
   // translated image. Unresolved originals remain visible in that final image.
   if(preparedPixels)for(const region of preparedClean.regions){const runs=region.inputRuns||region.runs||[];for(let n=0;n<runs.length;n+=2)cleanupMask.fill(1,runs[n],runs[n+1]);}
   const mc=new OffscreenCanvas(original.width,original.height),pixels=new ImageData(original.width,original.height);
   for(let n=0;n<cleanupMask.length;n++)if(cleanupMask[n])pixels.data.set([255,70,35,180],n*4);
   mc.getContext('2d').putImageData(pixels,0,0);
   debug={cleanedImage:preparedPixels?preparedClean.cleanedImage:await(await canvas.convertToBlob({type:'image/webp',quality:.95})).arrayBuffer(),cleanedMime:preparedPixels?'image/png':'image/webp',backgroundCleanup:!!preparedPixels,cleanupRegions:(preparedPixels?preparedClean.regions:records).map(r=>({uid:r.uid,painted:!!r.painted,reason:r.reason,translated:!!page.regions.find(p=>p.uid===r.uid)?.ru_translation?.trim()})),unresolved:unresolved.map(r=>r.uid),maskImage:await(await mc.convertToBlob({type:'image/png'})).arrayBuffer(),detected:{width:page.width,height:page.height,regions:page.regions.map(r=>({id:r.uid,bbox:r.text_bbox}))},coordinatesKind:'translation'};
  }
  // Typography is the last phase. Cleanup never reads these newly drawn glyphs.
  // Explicit readable fallback: never claim a failed cleanup succeeded. Paint
  // Russian black with a white, rounded ~3px backing around the actual glyphs.
  for(const[i,p]of plans.entries())if(!p.painted&&!conflicts.has(i)){p.fallback=true;const record=records.find(r=>r.uid===p.region.uid);if(record)record.fallback='white-lettering';}
  const layouts=[];for(const p of plans)if(p.painted||p.fallback){
   const t=performance.now(),{box,fit}=p,ink=comicInkColor(working,box),dark=!p.fallback&&ink.dark,complex=p.fallback||ink.outline||['sfx','sign','whisper_aside'].includes(p.region.text_category);
   if(p.layout){
    // A reply outside a balloon of paper is lettered with an outline, as the
    // original was: on a drawing plain letters cannot be read.
    const outside=!p.region.bubble_shape&&!p.region.bubble_bbox;
    drawLayout(ctx,p.layout,{face:p.face,angle:0,fill:dark?'#fff':'#151515',stroke:complex||outside?(dark?'#151515':'#fff'):null,strokeRatio:p.fallback?.18:outside?.15:.1});typesetMs+=performance.now()-t;
    layouts.push({uid:p.region.uid,font:p.idFont,role:p.role,voice:p.voice,shape:[Math.round(p.shape.width),Math.round(p.shape.height),p.region.bubble_shape?'paper':p.region.bubble_bbox?'detector':'box'],fontSize:Math.round(p.layout.size*10)/10,lines:p.layout.lines.length,hyphens:p.layout.hyphens,shrunk:p.layout.shrunk,color:dark?'#fff':'#151515',backgroundLuma:ink.luma,fallback:!!p.fallback,vertical:false,layoutBox:box,fits:true});continue;
   }
   ctx.save();ctx.beginPath();ctx.rect(box[0]-(p.fallback?3:0),box[1]-(p.fallback?3:0),box[2]-box[0]+(p.fallback?6:0),box[3]-box[1]+(p.fallback?6:0));ctx.clip();ctx.font=`${p.weight} ${fit.fontSize}px ${p.family}`;ctx.textAlign='center';ctx.textBaseline='top';ctx.fillStyle=dark?'#fff':'#151515';ctx.lineJoin='round';
   let cx=(box[0]+box[2])/2,cy=p.region.flow?box[1]-p.region.flow.offsetY+(p.region.flow.height-fit.blockH)/2:(box[1]+box[3]-fit.blockH)/2;
   if(p.vertical){ctx.translate(cx,(box[1]+box[3])/2);ctx.rotate(Math.PI/2);cx=0;cy=-fit.blockH/2;}
   for(const[n,line]of fit.lines.entries()){if(complex){ctx.strokeStyle=dark?'#151515':'#fff';ctx.lineWidth=p.fallback?Math.max(6,fit.fontSize*.18):Math.max(2,fit.fontSize*.16);ctx.strokeText(line,cx,cy+n*fit.lineH);}ctx.fillText(line,cx,cy+n*fit.lineH);}
   ctx.restore();typesetMs+=performance.now()-t;layouts.push({uid:p.region.uid,font:p.idFont,fontSize:fit.fontSize,lines:fit.lines.length,color:dark?'#fff':'#151515',backgroundLuma:ink.luma,fallback:!!p.fallback,vertical:!!p.vertical,layoutBox:box,fits:true});
  }
  const unpainted=records.filter(r=>!r.painted).length;
  if(unpainted)warnings.push('Фон восстановлен для '+records.filter(r=>r.painted).length+' из '+records.length+' областей. При неудачной очистке перевод показан с белой подложкой.');
  if(lamaUnavailable)warnings.push((mode==='moebius'?'Moebius':mode==='migan'||mode==='smart'?'MI-GAN':'LaMa')+': '+lamaUnavailable+(mode==='smart'?' Текст поверх рисунка очищен быстрым методом.':''));
  let cacheImage;if(cache&&!unpainted&&!unresolved.length)cacheImage=await(await canvas.convertToBlob({type:'image/webp',quality:.94})).arrayBuffer();
  const renderedBitmap=canvas.transferToImageBitmap();
  return {renderedBitmap,cacheImage,debug,warnings,typesetting:{engine:READER_TYPESETTER,baseSize,caps,layouts},inpaint:{requested:mode,strategy:mode==='moebius'?moebiusStrategy:'regions',modelCalls,execution:pageExecution,prepared:preparedClean?{cacheHit:!!preparedClean.cacheHit,inpaint:preparedClean.inpaint,timings:preparedClean.timings}:undefined,methods:[...methods],unpainted,regions:records},timings:{...page.timings,inpaintMs,typesetMs,renderMs:performance.now()-start},regions:page.regions.map(r=>({id:r.uid,text:r.ru_translation,original:r.source_text,x:r.text_bbox[0]/page.width,y:r.text_bbox[1]/page.height,w:(r.text_bbox[2]-r.text_bbox[0])/page.width,h:(r.text_bbox[3]-r.text_bbox[1])/page.height})),usage:page.usage,engine:page.engine||'Перевод → очистка → русский набор',cacheHit:page.cacheHit};
 }finally{bitmap.close();}
}
