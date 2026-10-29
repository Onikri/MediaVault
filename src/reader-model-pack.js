export async function prepareReaderModels(config,status){
 if(!['direct','vm'].includes(config.engine))throw Error('Предзагрузка пакета доступна для режимов Google. Локальный LMT загружает свой набор при запуске.');
 const {DefaultConfig}=await import('../lmt/upstream/lib/configs.ts');
 const {downloadArtifactHF}=await import('../lmt/upstream/lib/utils.ts');
 const files=[];
 if(config.directInput!=='vision'){
  if(config.directDetector==='rtdetr')files.push([DefaultConfig.rtdetrModelRepo,'detector-v4-s_int8.onnx']);
  if(config.directDetector==='ctd')files.push([DefaultConfig.comicTextDetectorUrl,'']);
  if(config.directDetector==='yolo26n-manga')files.push(['https://huggingface.co/mednasserallah/manga-panel-detector-yolo26n-onnx/resolve/f6b7f3cb2bada1ec7d8b16501f9c984890811445/manga_panel_detector_fp32_1024.onnx','']);
  if(config.directDetector==='ppocrv6-det')files.push(['https://huggingface.co/Kellenok/PP-OCRv6_manga/resolve/62375557b5b0a4b2bc8e05484a97c7ea1df7229e/det/manga_det_v0.2.onnx','']);
 }
 if(['hybrid','quality'].includes(config.inpaint))files.push([DefaultConfig.lamaRepo,DefaultConfig.lamaModelPath]);
 let count=0;
 for(const[repo,path]of files){
  status({message:'Проверка / загрузка '+(path||repo.split('/').at(-1)),loaded:0,total:0});
  await downloadArtifactHF(path?repo:'',path||repo,true,{onProgress:(loaded,total)=>status({loaded,total,message:'Загрузка '+(path||repo.split('/').at(-1))+(total?' · '+Math.round(loaded/total*100)+'%':'')})});count++;
 }
 if(config.inpaint==='moebius'){
  const {loadModelBytes}=await import('../lmt/moebius/modelcache.ts');
  for(const name of ['vae_encoder.onnx','vae_decoder.onnx','unet.onnx']){
   await loadModelBytes('https://huggingface.co/simonw/Moebius-ONNX/resolve/5bf1ef5d2861ec01a727183a3f95dc64f352120e/'+name,(loaded,total,cached)=>status({loaded,total,message:(cached?'Из кэша: ':'Загрузка: ')+name+(total?' · '+Math.round(loaded/total*100)+'%':'')}));count++;
  }
 }
 return count;
}
