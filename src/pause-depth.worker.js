import {depthInput,normalizeDepth} from './pause-depth-model.js';
import {depthWeights} from './pause-depth-cache.js';
let runtime;
async function initialize(id){
 let lastProgress=0;const bytes=await depthWeights(status=>{const now=performance.now();if(status.phase!=='download'||status.loaded===0||status.loaded===status.total||now-lastProgress>=100){lastProgress=now;postMessage({id,type:'status',...status});}});
 const ort=await import('onnxruntime-web/wasm');ort.env.wasm.numThreads=1;
 ort.env.wasm.wasmPaths=new URL(/* @vite-ignore */ '../lmt/',import.meta.url).href;
 postMessage({id,type:'status',phase:'initialize'});
 const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm'],graphOptimizationLevel:'all'});
 return {ort,session};
}
self.onmessage=async({data})=>{
 const {id,width,height,pixels}=data;let input,outputs;
 try{
  if(!runtime)runtime=initialize(id).catch(e=>{runtime=null;throw e;});
  const {ort,session}=await runtime;postMessage({id,type:'status',phase:'inference'});
  input=new ort.Tensor('float32',depthInput(new Uint8ClampedArray(pixels),width,height),[1,3,height,width]);
  const start=performance.now();outputs=await session.run({[session.inputNames[0]]:input});const output=outputs[session.outputNames[0]],values=await output.getData(),dims=output.dims;
  const w=dims.at(-1),h=dims.at(-2);if(!w||!h||w*h!==values.length)throw Error('Некорректная карта глубины.');
  const depth=normalizeDepth(values);postMessage({id,type:'result',width:w,height:h,depth:depth.buffer,inferenceMs:performance.now()-start,provider:'wasm'},[depth.buffer]);
 }catch(e){postMessage({id,type:'error',message:/[А-Яа-яЁё]/.test(e.message||'')?e.message.slice(0,240):'Не удалось подготовить глубину. Проверь сеть и повтори.'});}
 finally{input?.dispose();if(outputs)for(const value of Object.values(outputs))value.dispose?.();}
};
