// SPDX-License-Identifier: AGPL-3.0-or-later
// Private backend bindings. Ordinary browser/device inference keeps upstream ORT.
import * as ort from 'onnxruntime-web/all';
const constructors: Record<string, any> = {
 float32: Float32Array, float64: Float64Array, float16: Uint16Array,
 int64: BigInt64Array, uint64: BigUint64Array, int32: Int32Array,
 uint32: Uint32Array, int16: Int16Array, uint16: Uint16Array,
 int8: Int8Array, uint8: Uint8Array, bool: Uint8Array,
};
function encode(data: ArrayBufferView) {
 const bytes=new Uint8Array(data.buffer,data.byteOffset,data.byteLength);let text='';
 for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));
 return btoa(text);
}
export async function createNativeSession(url: string, sha: string | null): Promise<ort.InferenceSession | null> {
 const bridge=globalThis as any;
 if(typeof bridge.mvOrtCreate!=='function')return null;
 if(!sha)throw Error('Native ONNX requires a pinned model hash');
 const metadata=await bridge.mvOrtCreate({url,sha});
 return {...metadata, async run(feeds: Record<string, ort.Tensor>) {
   const encoded: Record<string, any>={};
   for(const [name,tensor] of Object.entries(feeds))encoded[name]={type:tensor.type,dims:[...tensor.dims],data:encode(await tensor.getData() as ArrayBufferView)};
   const result=await bridge.mvOrtRun({id:metadata.id,feeds:encoded});const decoded: Record<string, ort.Tensor>={};
   for(const [name,value] of Object.entries(result) as [string,any][]){
    const bytes=Uint8Array.from(atob(value.data),c=>c.charCodeAt(0));
    const Constructor=constructors[value.type];if(!Constructor)throw Error('Unsupported native tensor type');
    decoded[name]=new ort.Tensor(value.type,new Constructor(bytes.buffer),value.dims);
   }
   return decoded;
  }, async release(){await bridge.mvOrtRelease({id:metadata.id});}
 } as unknown as ort.InferenceSession;
}
