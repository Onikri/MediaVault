// Lazy model adapter: the reader worker remains independent of the old iframe
// and loads no OCR/LLM. The upstream LaMa graph uses WASM (FFC lacks WebGPU ops).
let loading;
export async function inpaintLamaPatch(image,mask,status=()=>{}){
 if(!loading)loading=(async()=>{
  status('LaMa Manga · загрузка модели 206 МБ и запуск, один раз');
  const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;
  ort.env.wasm.wasmPaths=new URL(/* @vite-ignore */ '../lmt/',import.meta.url).href;
  return import('../lmt/upstream/lib/inpaint/lama.ts');
 })().catch(e=>{loading=null;throw e;});
 const model=await loading;
 const ok=await model.renderLama(image,{ink:{data:mask,w:image.width,h:image.height,ox:0,oy:0}});
 if(!ok)throw Error(model.getLastLamaError()||'LaMa не восстановила область');
 return true;
}
