export const TITLE_UPSCALE={name:'IllustrationJaNai V3detail SPAN-S 2×',bytes:1673274,sha256:'3f5245ed1abe8ba2b5249b70989757a086874ee6346bdf33a71c21701a4b663d',file:'illustration-span-3f5245ed1abe.onnx',source:'https://github.com/the-database/MangaJaNai/releases/tag/3.0.0',license:'CC-BY-NC-4.0'};
export const TITLE_UPSCALE_MODELS={
 detail:{...TITLE_UPSCALE,id:'detail',label:'SPAN · детали и цвет',channels:3,maxInput:384},
 denoise:{id:'denoise',name:'IllustrationJaNai V3denoise SPAN-S 2×',label:'SPAN · шум и растр',bytes:1673274,sha256:'9d2c5ff9ea794d77976e69d41d9b84ffc99d4a2f0c7c11ba2eb05e040a2b69b6',file:'illustration-denoise-9d2c5ff9ea79.onnx',channels:3,maxInput:384,source:TITLE_UPSCALE.source,license:TITLE_UPSCALE.license},
 fast:{id:'fast',name:'FSRCNN 2×',label:'FSRCNN · быстрый CPU',bytes:35054,sha256:'313fe4371950fd90216db4d1ce6a8c9b513128c4e715b2363a11d6a52ccb0e36',file:'fsrcnn-313fe4371950.onnx',channels:1,maxInput:768,source:'https://github.com/televisualarts-cloud/wefax_decoder/tree/main/wefax/models',license:'Apache-2.0'},
};
export const titleUpscaleModel=id=>TITLE_UPSCALE_MODELS[id]||TITLE_UPSCALE_MODELS.detail;
