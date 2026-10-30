// One neural engine shares ONNX sessions and progress state across pages.
// Keep callers asynchronous while admitting inference in FIFO order.
export function serializePipeline(run){
 let tail=Promise.resolve();
 return (...args)=>{const task=tail.then(()=>run(...args));tail=task.catch(()=>{});return task;};
}
