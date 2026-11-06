// Real-ESRGAN AnimeVideo-v3 (SRVGGNetCompact, x4; BSD-3-Clause, xinntao/Real-ESRGAN),
// ONNX export pinned by SHA-256. The whole frame stays on the GPU: video -> WebGPU texture
// -> NCHW tensor buffer (compute) -> ONNX Runtime WebGPU -> output buffer -> canvas.
import {loadRuntime} from './neural-upscaler.js';

const MODEL='https://huggingface.co/skillsafe-ai/realesr-animevideov3/resolve/185e9142d439d17e3fb99395600fb7d08af09de5/model.onnx';
const MODEL_SHA256='78baa685a1a92cac6e14ab2af2a8ad0ef56fa48629563b1414e3a7acc54d86e2';
export const REALESRGAN_SOURCE='https://github.com/xinntao/Real-ESRGAN (realesr-animevideov3), ONNX: https://huggingface.co/skillsafe-ai/realesr-animevideov3';
// Network input height per load mode; output is four times larger.
const INPUT_HEIGHT={performance:360,balanced:480,quality:540};
let sessionPromise;

async function sha256(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');}
async function session(ort){
  if(!sessionPromise)sessionPromise=(async()=>{
    const response=await fetch(MODEL,{mode:'cors',cache:'force-cache'});
    if(!response.ok)throw Error('Модель Real-ESRGAN не загрузилась: HTTP '+response.status);
    const bytes=new Uint8Array(await response.arrayBuffer());
    if(await sha256(bytes)!==MODEL_SHA256)throw Error('Контрольная сумма модели Real-ESRGAN не совпала.');
    return ort.InferenceSession.create(bytes,{executionProviders:['webgpu'],graphOptimizationLevel:'all',preferredOutputLocation:'gpu-buffer'});
  })().catch(error=>{sessionPromise=null;throw error;});
  return sessionPromise;
}

const PACK=`@group(0) @binding(0) var src:texture_2d<f32>;
@group(0) @binding(1) var samp:sampler;
@group(0) @binding(2) var<storage,read_write> dst:array<f32>;
@group(0) @binding(3) var<uniform> dims:vec2u;
@compute @workgroup_size(16,16) fn main(@builtin(global_invocation_id) id:vec3u){
  if(id.x>=dims.x||id.y>=dims.y){return;}
  let c=textureSampleLevel(src,samp,(vec2f(id.xy)+.5)/vec2f(dims),0.);
  let n=dims.x*dims.y;let i=id.y*dims.x+id.x;
  dst[i]=c.r;dst[n+i]=c.g;dst[2u*n+i]=c.b;
}`;
const SHOW=`@group(0) @binding(0) var<storage,read> img:array<f32>;
@group(0) @binding(1) var<uniform> dims:vec2u;
@vertex fn vs(@builtin(vertex_index) i:u32)->@builtin(position) vec4f{let p=array(vec2f(-1.,-1.),vec2f(3.,-1.),vec2f(-1.,3.));return vec4f(p[i],0.,1.);}
@fragment fn fs(@builtin(position) pos:vec4f)->@location(0) vec4f{
  let p=vec2u(pos.xy);let n=dims.x*dims.y;let i=min(p.y,dims.y-1u)*dims.x+min(p.x,dims.x-1u);
  return vec4f(clamp(vec3f(img[i],img[n+i],img[2u*n+i]),vec3f(0.),vec3f(1.)),1.);
}`;

export async function startRealEsrgan(video,canvas,{mode='balanced',onStats=()=>{},onFailure=()=>{}}={}){
  if(!navigator.gpu)throw Error('Нужен браузер с WebGPU: Chrome или Edge и совместимая видеокарта.');
  const ort=await loadRuntime();
  const net=await session(ort);
  const device=await ort.env.webgpu.device;
  if(!device)throw Error('ONNX Runtime не отдал устройство WebGPU.');
  if(video.readyState<2)await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('Нет кадра видео для улучшения.')),10000);video.addEventListener('loadeddata',()=>{clearTimeout(t);resolve();},{once:true});});
  const context=canvas.getContext('webgpu');if(!context)throw Error('Холст не поддерживает WebGPU.');
  const format=navigator.gpu.getPreferredCanvasFormat();
  context.configure({device,format,alphaMode:'opaque'});
  const sampler=device.createSampler({magFilter:'linear',minFilter:'linear'});
  const pack=device.createComputePipeline({layout:'auto',compute:{module:device.createShaderModule({code:PACK}),entryPoint:'main'}});
  const show=device.createRenderPipeline({layout:'auto',vertex:{module:device.createShaderModule({code:SHOW}),entryPoint:'vs'},fragment:{module:device.createShaderModule({code:SHOW}),entryPoint:'fs',targets:[{format}]},primitive:{topology:'triangle-list'}});
  let plan=null,stopped=false,busy=false,frame=0,frames=0,since=performance.now(),last=-1;
  function layout(vw,vh){
    plan?.destroy();
    const h=Math.min(vh,INPUT_HEIGHT[mode]||480),w=Math.round(h*vw/vh/2)*2,W=w*4,H=h*4;
    const frameTex=device.createTexture({size:[vw,vh],format:'rgba8unorm',usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT});
    const input=device.createBuffer({size:3*w*h*4,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST});
    const inDims=device.createBuffer({size:8,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});device.queue.writeBuffer(inDims,0,new Uint32Array([w,h]));
    const outDims=device.createBuffer({size:8,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});device.queue.writeBuffer(outDims,0,new Uint32Array([W,H]));
    const packGroup=device.createBindGroup({layout:pack.getBindGroupLayout(0),entries:[{binding:0,resource:frameTex.createView()},{binding:1,resource:sampler},{binding:2,resource:{buffer:input}},{binding:3,resource:{buffer:inDims}}]});
    canvas.width=W;canvas.height=H;
    plan={vw,vh,w,h,W,H,frameTex,input,outDims,packGroup,tensor:ort.Tensor.fromGpuBuffer(input,{dataType:'float32',dims:[1,3,h,w]}),destroy(){frameTex.destroy();input.destroy();inDims.destroy();outDims.destroy();}};
  }
  async function render(){
    if(stopped||busy||video.readyState<2||video.currentTime===last)return;
    busy=true;last=video.currentTime;const start=performance.now();
    try{
      if(!plan||plan.vw!==video.videoWidth||plan.vh!==video.videoHeight)layout(video.videoWidth,video.videoHeight);
      device.queue.copyExternalImageToTexture({source:video},{texture:plan.frameTex},[plan.vw,plan.vh]);
      const encoder=device.createCommandEncoder(),pass=encoder.beginComputePass();
      pass.setPipeline(pack);pass.setBindGroup(0,plan.packGroup);pass.dispatchWorkgroups(Math.ceil(plan.w/16),Math.ceil(plan.h/16));pass.end();
      device.queue.submit([encoder.finish()]);
      const result=await net.run({[net.inputNames[0]]:plan.tensor});
      const output=result[net.outputNames[0]];
      if(stopped){output.dispose();return;}
      const group=device.createBindGroup({layout:show.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:output.gpuBuffer}},{binding:1,resource:{buffer:plan.outDims}}]});
      const draw=device.createCommandEncoder(),rp=draw.beginRenderPass({colorAttachments:[{view:context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store',clearValue:[0,0,0,1]}]});
      rp.setPipeline(show);rp.setBindGroup(0,group);rp.draw(3);rp.end();device.queue.submit([draw.finish()]);
      await device.queue.onSubmittedWorkDone();output.dispose();
      canvas.style.opacity='1';frames++;
      const now=performance.now();if(now-since>1000){onStats({engine:'Real-ESRGAN',width:plan.W,height:plan.H,fps:Math.round(frames*1000/(now-since)),latency:Math.round(now-start)});frames=0;since=now;}
    }catch(error){stop();onFailure(error instanceof Error?error:Error(String(error)));}
    finally{busy=false;}
  }
  function tick(){frame=0;if(stopped)return;render();frame=video.requestVideoFrameCallback?video.requestVideoFrameCallback(tick):requestAnimationFrame(tick);}
  const refresh=()=>{last=-1;render();};
  function stop(){if(stopped)return;stopped=true;if(video.cancelVideoFrameCallback)video.cancelVideoFrameCallback(frame);else cancelAnimationFrame(frame);video.removeEventListener('seeked',refresh);plan?.destroy();canvas.style.opacity='0';try{context.unconfigure();}catch{}}
  video.addEventListener('seeked',refresh);
  tick();await render();
  return stop;
}
