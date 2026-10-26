// Official Tencent Hy-MT2, Apache-2.0. Revision and LFS SHA-256 are immutable.
export const HYMT_REVISION='a0c709d9fac510f2c807aa3af52872340dc37a4a';
export const HYMT_MODELS={
 q8:{id:'q8',file:'Hy-MT2-1.8B-Q8_0.gguf',bytes:1908528192,sha:'5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4',label:'Q8 · качество, как на ВМ · 1,91 ГБ'},
 q6:{id:'q6',file:'Hy-MT2-1.8B-Q6_K.gguf',bytes:1474785120,sha:'d98fe604dec1f28f58f80d7d560f7177e584d3b8e5835862687660e5ff97cb40',label:'Q6 · меньше памяти · 1,47 ГБ'},
 q4:{id:'q4',file:'Hy-MT2-1.8B-Q4_K_M.gguf',bytes:1133080448,sha:'dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699',label:'Q4 · для ограниченной памяти · 1,13 ГБ'},
};
export function hymtModel(id='q8'){return HYMT_MODELS[id]||HYMT_MODELS.q8;}
export function hymtUrl(model){return 'https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/'+HYMT_REVISION+'/'+model.file;}
export function hymtPrompt(text){return 'Translate the following text into Russian. Note that you should only output the translated result without any additional explanation:\n\n'+text;}
