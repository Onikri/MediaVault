// Real, trained x2 super-resolution: FSRCNN ONNX (Apache-2.0 pretrained
// weights). ONNX Runtime Web WebGPU executes the convolutional neural network.
// No "sharpen" shader or non-neural substitution is used.
const RUNTIME = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.30.0/dist/';
const MODEL = 'https://raw.githubusercontent.com/televisualarts-cloud/wefax_decoder/main/wefax/models/fsrcnn_x2.onnx';
// Immutable content pin: upstream Git blob hash for the 35,054-byte model.
// Downloaded weights are verified *before* creating a GPU inference session.
export const MODEL_BLOB_SHA1 = '0ce756653b71056586ab508710135f4a3c967214';
export const MODEL_SOURCE = 'https://github.com/televisualarts-cloud/wefax_decoder/blob/main/wefax/models/fsrcnn_x2.onnx';
export const QUALITY_MODES = Object.freeze({
  performance: {width:320, interval:83},
  balanced: {width:480, interval:66},
  quality: {width:640, interval:50}
});
let runtimePromise, modelPromise;
function aborted(){return new DOMException('Neural upscaling stopped','AbortError');}

export async function gitBlobSha1(bytes) {
  const raw = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const header = new TextEncoder().encode('blob ' + raw.byteLength + '\0');
  const packed = new Uint8Array(header.length + raw.length);
  packed.set(header); packed.set(raw,header.length);
  const digest = await crypto.subtle.digest('SHA-1',packed);
  return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
}
async function loadRuntime() {
  if(!navigator.gpu) throw Error('Нужен браузер с WebGPU (Chromium/Chrome/Edge и совместимая видеокарта).');
  if(window.ort?.InferenceSession) return window.ort;
  if(!runtimePromise){
    runtimePromise = new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.async=true; script.src=RUNTIME+'ort.webgpu.min.js';
      script.crossOrigin='anonymous';
      script.onload=()=>{
        if(!window.ort?.InferenceSession)reject(Error('ONNX Runtime Web не загрузился.'));
        else{
          window.ort.env.wasm.wasmPaths=RUNTIME;
          resolve(window.ort);
        }
      };
      script.onerror=()=>reject(Error('Не удалось загрузить ONNX Runtime Web.'));
      document.head.appendChild(script);
    }).catch(error=>{runtimePromise=null;throw error;});
  }
  return runtimePromise;
}
async function modelBytes(){
  if(!modelPromise){
    modelPromise=(async()=>{
      const response=await fetch(MODEL,{mode:'cors',cache:'force-cache'});
      if(!response.ok)throw Error('Модель FSRCNN не загружена: HTTP '+response.status);
      const bytes=new Uint8Array(await response.arrayBuffer());
      if(bytes.byteLength!==35054||await gitBlobSha1(bytes)!==MODEL_BLOB_SHA1)
        throw Error('Контрольная сумма весов FSRCNN не совпала.');
      return bytes;
    })().catch(error=>{modelPromise=null;throw error;});
  }
  return modelPromise;
}
export function prepareLuma(image) {
  const {width,height,data}=image;
  if(!Number.isSafeInteger(width)||!Number.isSafeInteger(height)||width<=0||height<=0||
    data.length!==width*height*4)throw Error('Некорректный кадр для нейросети.');
  const output=new Float32Array(width*height);
  for(let p=0,i=0;p<output.length;p++,i+=4){
    output[p]=(0.299*data[i]+0.587*data[i+1]+0.114*data[i+2])/255;
  }
  return output;
}
/** Upsample chroma with canvas interpolation, replace brightness with actual
 * neural inference; the FSRCNN checkpoint is trained on the Y channel. */
export function reconstructRgb(baseRgb,neuralY) {
  const result=new Uint8ClampedArray(baseRgb.length);
  if(baseRgb.length!==neuralY.length*4)throw Error('Unexpected model output dimensions.');
  for(let p=0,i=0;p<neuralY.length;p++,i+=4){
    const y=0.299*baseRgb[i]+0.587*baseRgb[i+1]+0.114*baseRgb[i+2];
    const target=Math.max(0,Math.min(1,neuralY[p]))*255;
    const delta=target-y;
    result[i]=baseRgb[i]+delta;
    result[i+1]=baseRgb[i+1]+delta;
    result[i+2]=baseRgb[i+2]+delta;
    result[i+3]=255;
  }
  return result;
}
export async function startNeuralUpscaler(video,canvas,{mode='balanced',onFailure=()=>{},onStats=()=>{}}={}) {
  const settings=QUALITY_MODES[mode]||QUALITY_MODES.balanced;
  const ort=await loadRuntime();
  const adapter=await navigator.gpu?.requestAdapter({powerPreference:'high-performance'});
  if(!adapter)throw Error('Производительный WebGPU-адаптер недоступен.');
  const gpuInfo=adapter.info||{};
  const device=await adapter.requestDevice();
  ort.env.webgpu.device=device;
  const model=await modelBytes();
  const session=await ort.InferenceSession.create(model,{
    executionProviders:['webgpu'],graphOptimizationLevel:'all'
  });
  // Verify that the browser actually runs the pretrained model on its WebGPU
  // device before the UI reports active AI upscaling.
  try{
    const testFeed=new ort.Tensor('float32',new Float32Array(32*32),[1,1,32,32]);
    const testOutput=await session.run({[session.inputNames[0]]:testFeed});
    const probe=testOutput[session.outputNames[0]];
    if(!probe||probe.dims[2]!==64||probe.dims[3]!==64)
      throw Error('FSRCNN self-test returned an invalid tensor.');
  }catch(error){
    await session.release();device.destroy();
    throw Error('Проверка GPU-инференса FSRCNN не прошла: '+error.message);
  }
  let stopped=false,busy=false,callbackId=0,videoCallback=false,last=0,slow=0;
  let total=0,lastStats=performance.now(),captured=0;
  const input=document.createElement('canvas'),base=document.createElement('canvas');
  const inCtx=input.getContext('2d',{willReadFrequently:true});
  const baseCtx=base.getContext('2d',{willReadFrequently:true});
  const outputCtx=canvas.getContext('2d',{alpha:false});
  if(!inCtx||!baseCtx||!outputCtx){await session.release();device.destroy();throw Error('Canvas 2D недоступен.');}
  function stop(){
    if(stopped)return;
    stopped=true;
    if(callbackId){
      if(videoCallback)video.cancelVideoFrameCallback?.(callbackId);
      else cancelAnimationFrame(callbackId);
    }
    video.removeEventListener('seeked',clearFrame);
    video.removeEventListener('emptied',clearFrame);
    document.removeEventListener('visibilitychange',visibility);
    canvas.style.opacity='0';
    // The in-flight run must complete before session resources are released.
    if(!busy)session.release().catch(()=>{}).finally(()=>device.destroy());
  }
  function fail(error){if(stopped)return;stop();onFailure(error);}
  function clearFrame(){canvas.style.opacity='0';last=0;}
  function visibility(){if(document.hidden)clearFrame();}
  const tick=async()=>{
    if(stopped)return;
    schedule(); // Don't block the video pipeline on an inference completion.
    if(busy||document.hidden||video.paused||video.ended||video.readyState<2||
      !video.videoWidth||performance.now()-last<settings.interval)return;
    busy=true;const started=performance.now(),frameTime=video.currentTime;
    last=started;
    try{
      // Maintain the original aspect ratio, with bounded NN input size and VRAM.
      const w=Math.max(16,Math.round(Math.min(settings.width,video.videoWidth)/8)*8);
      const h=Math.max(16,Math.round(w*video.videoHeight/video.videoWidth/8)*8);
      const ow=w*2,oh=h*2;
      if(input.width!==w||input.height!==h){input.width=w;input.height=h;}
      if(base.width!==ow||base.height!==oh){base.width=ow;base.height=oh;}
      inCtx.drawImage(video,0,0,w,h);
      const frame=inCtx.getImageData(0,0,w,h);
      const feed=new ort.Tensor('float32',prepareLuma(frame),[1,1,h,w]);
      const result=await session.run({[session.inputNames[0]]:feed});
      const output=result[session.outputNames[0]];
      if(!output||output.dims[2]!==oh||output.dims[3]!==ow)
        throw Error('Модель FSRCNN вернула неожиданный размер результата.');
      if(stopped)return;
      // Drop frames invalidated by seek, source switches, or a stale inference.
      if(Math.abs(video.currentTime-frameTime)>0.5){clearFrame();return;}
      baseCtx.imageSmoothingEnabled=true;
      baseCtx.imageSmoothingQuality='high';
      baseCtx.drawImage(input,0,0,ow,oh);
      const baseFrame=baseCtx.getImageData(0,0,ow,oh);
      const pixels=reconstructRgb(baseFrame.data,output.data);
      if(canvas.width!==ow||canvas.height!==oh){canvas.width=ow;canvas.height=oh;}
      outputCtx.putImageData(new ImageData(pixels,ow,oh),0,0);
      canvas.style.opacity='1';
      const elapsed=performance.now()-started;
      total++;
      // Skip excessive GPU work; don't claim real-time when inference is too slow.
      slow=elapsed>240?slow+1:Math.max(0,slow-1);
      if(slow>=4)throw Error('FSRCNN слишком медленная на этом GPU. Выбери экономный режим.');
      const now=performance.now();
      if(now-lastStats>=1000){
        onStats({adapter:gpuInfo.description||gpuInfo.device||gpuInfo.vendor||'WebGPU (название скрыто браузером)',fps:Math.round(total*1000/(now-lastStats)),latency:Math.round(elapsed),width:ow,height:oh});
        lastStats=now;total=0;
      }
    }catch(error){fail(error);}
    finally{
      busy=false;
      if(stopped)session.release().catch(()=>{}).finally(()=>device.destroy());
    }
  };
  function schedule(){
    if(stopped||document.hidden)return;
    videoCallback=typeof video.requestVideoFrameCallback==='function';
    callbackId=videoCallback?video.requestVideoFrameCallback(tick):requestAnimationFrame(tick);
  }
  video.addEventListener('seeked',clearFrame);
  video.addEventListener('emptied',clearFrame);
  document.addEventListener('visibilitychange',visibility);
  schedule();
  return stop;
}
