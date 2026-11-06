// WebGPU upscalers for anime: Anime4K mode chains, ArtCNN, CuNNy and ACNet.
// The compute pipelines come from NijiLucid (vendored in src/vendor/nijilucid; core MIT,
// CuNNy-derived parts LGPL-3.0-or-later), which ports the upstream mpv shaders to WGSL.
// Same contract as the other engines: start(video, canvas, options) resolves to stop().

const A4K_TIERS={performance:'performance',balanced:'balanced',quality:'quality'};
// Our profile id -> NijiLucid effect ids (or an Anime4K preset mode).
export const WEBGPU_PROFILES={
  'a4k-a':{preset:'A'},'a4k-b':{preset:'B'},'a4k-c':{preset:'C'},
  'a4k-aa':{preset:'A+A'},'a4k-bb':{preset:'B+B'},'a4k-ca':{preset:'C+A'},
  'artcnn-c4f16':{ids:['artcnn/Upscale/C4F16']},'artcnn-c4f16-ds':{ids:['artcnn/Upscale/C4F16_DS']},'artcnn-c4f16-dn':{ids:['artcnn/Upscale/C4F16_DN']},
  'artcnn-c4f32':{ids:['artcnn/Upscale/C4F32']},'artcnn-c4f32-ds':{ids:['artcnn/Upscale/C4F32_DS']},'artcnn-c4f32-dn':{ids:['artcnn/Upscale/C4F32_DN']},
  'cunny-veryfast':{ids:['cunny/Upscale/SOFT/Veryfast']},'cunny-faster':{ids:['cunny/Upscale/SOFT/Faster']},'cunny-fast':{ids:['cunny/Upscale/SOFT/Fast']},
  'cunny-4x16':{ids:['cunny/Upscale/SOFT/4x16']},'cunny-4x32':{ids:['cunny/Upscale/SOFT/4x32']},'cunny-fast-ds':{ids:['cunny/Upscale/DS/Fast']},'cunny-8x32-ds':{ids:['cunny/Upscale/DS/8x32']},
  'acnet-f8b8':{ids:['acnet/Upscale/F8B8']},'acnet-f8b18':{ids:['acnet/Upscale/F8B18']},'acnet-f8b18-hdn':{ids:['acnet/Upscale/F8B18_HDN']}
};
export const isWebGpuProfile=id=>Object.hasOwn(WEBGPU_PROFILES,id);

function targetSize(video,canvas,scale){
  const w=video.videoWidth||1280,h=video.videoHeight||720;
  // Render no bigger than the screen area the picture occupies (and never past 4K).
  const box=canvas.parentElement?.getBoundingClientRect(),dpr=Math.min(2,devicePixelRatio||1);
  const room=box?Math.max(box.width*dpr,box.height*dpr*w/h):w*scale;
  const width=Math.round(Math.min(w*scale,Math.max(w,room),3840));
  return {width,height:Math.round(width*h/w)};
}

export async function startWebGpuUpscaler(video,canvas,{profile,mode='balanced',onStats=()=>{},onFailure=()=>{}}={}){
  if(!navigator.gpu)throw Error('Нужен браузер с WebGPU: Chrome или Edge и совместимая видеокарта.');
  const spec=WEBGPU_PROFILES[profile];if(!spec)throw Error('Неизвестный профиль улучшения.');
  // The engine reads its progress strings through the extension i18n API.
  globalThis.chrome=globalThis.chrome||{};globalThis.chrome.i18n=globalThis.chrome.i18n||{getMessage:()=>''};
  const [{Renderer},registry,{createEffectReference},{createEffectSignature}]=await Promise.all([
    import('./vendor/nijilucid/core/renderer/index.ts'),
    import('./vendor/nijilucid/core/effects/registry.ts'),
    import('./vendor/nijilucid/core/effects/reference.ts'),
    import('./vendor/nijilucid/utils/effect-signature.ts')
  ]);
  const effects=spec.preset?registry.resolvePresetEffects('anime4k',spec.preset,A4K_TIERS[mode]||'balanced')
    :spec.ids.map(id=>{const d=registry.getEffectDescriptorById(id);if(!d)throw Error('Модель '+id+' не найдена.');return createEffectReference(d);});
  const scale=effects.reduce((s,e)=>s*((registry.getEffectDescriptor(e)?.dimensionBehavior?.scale)||1),1);
  let renderer=null,stopped=false,stats={frames:0,since:performance.now()};
  const fail=error=>{if(stopped)return;stop();onFailure(error instanceof Error?error:Error(String(error)));};
  const target=targetSize(video,canvas,scale);canvas.width=target.width;canvas.height=target.height;
  try{
    renderer=await Renderer.create({
      video,canvas,effects,effectsSignature:createEffectSignature(effects),targetDimensions:target,
      performanceMonitorMode:'lite',performanceTier:A4K_TIERS[mode]||'balanced',performanceModeName:profile,
      onError:fail,
      onFirstFrameRendered:()=>{if(!stopped)canvas.style.opacity='1';},
      onPerformanceSnapshot:s=>{const now=performance.now();stats.frames++;if(now-stats.since>1000){stats.since=now;onStats({renderer:s.gpuName,engine:profile,width:s.targetDimensions?.width,height:s.targetDimensions?.height,fps:Math.round(s.fps||0),latency:Math.round(s.frameMs||0)});}}
    });
  }catch(error){throw error instanceof Error?error:Error(String(error));}
  if(stopped){renderer.destroy();}
  function stop(){if(stopped)return;stopped=true;try{renderer?.destroy();}catch{}canvas.style.opacity='0';}
  return stop;
}
