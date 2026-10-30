// Official author-provided MI-GAN ONNX pipeline; code and weights are MIT.
export const MIGAN_MODEL={url:'https://huggingface.co/andraniksargsyan/migan/resolve/406830d0fa60666da0071c342ad2fbc8f30c5c64/migan_pipeline_v2.onnx',bytes:28079181,sha256:'6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b'};
export function miganInputs(image,mask){
 const plane=image.width*image.height;
 if(mask.length!==plane)throw Error('Некорректная маска MI-GAN');
 const rgb=new Uint8Array(plane*3),known=new Uint8Array(plane);
 for(let n=0;n<plane;n++){for(let c=0;c<3;c++)rgb[c*plane+n]=image.data[n*4+c];known[n]=mask[n]?0:255;}
 return {rgb,known}; // ONNX uint8 NCHW; 0=hole, 255=known (opposite to LaMa)
}
export function applyMiganOutput(image,mask,values){
 const plane=image.width*image.height;
 if(values.length!==plane*3)throw Error('Некорректный ответ MI-GAN');
 for(let n=0;n<plane;n++)if(mask[n])for(let c=0;c<3;c++)image.data[n*4+c]=values[c*plane+n];
}
