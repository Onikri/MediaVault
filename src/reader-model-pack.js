export async function prepareReaderModels(config,status){
 const local=config.engine==='lmt';
 if(!['direct','vm','lmt'].includes(config.engine))throw Error('Серверные модели хранятся на ВМ. Выбери локальный режим для пакета устройства.');
 if(local&&config.deviceTranslator==='webllm')throw Error('Экспериментальный WebLLM загружает собственный пакет в кэш браузера при первом запуске. Для выбранной папки используй Hy-MT2 или Index.');
 const {DefaultConfig}=await import('../lmt/upstream/lib/configs.ts');
 const {downloadArtifactHF}=await import('../lmt/upstream/lib/utils.ts');
 const files=[];
 const detector=local?({'comic-bubble':'rtdetr','comic-text-detector':'ctd'}[config.detector]||config.detector):config.directDetector;
 if(local||!['vision','blocks'].includes(config.directInput)){
  if(detector==='rtdetr')files.push([DefaultConfig.rtdetrModelRepo,'detector-v4-s_int8.onnx']);
  if(detector==='ctd')files.push([DefaultConfig.comicTextDetectorUrl,'']);
  if(detector==='yolo26n-manga')files.push(['https://huggingface.co/mednasserallah/manga-panel-detector-yolo26n-onnx/resolve/f6b7f3cb2bada1ec7d8b16501f9c984890811445/manga_panel_detector_fp32_1024.onnx','']);
  if(detector==='ppocrv6-det')files.push(['https://huggingface.co/Kellenok/PP-OCRv6_manga/resolve/62375557b5b0a4b2bc8e05484a97c7ea1df7229e/det/manga_det_v0.2.onnx','']);
 }
 if(local){
  const {resolveMangaOcr}=await import('./ocr-profiles.js'),ocr=resolveMangaOcr(config.language,config.ocr);
  files.push([DefaultConfig.gateRepo,DefaultConfig.gateModelPath],[DefaultConfig.gateRepo,DefaultConfig.gateLabelsPath]);
  if(ocr==='manga-ocr')for(const file of ['encoder_model.onnx','decoder_model.onnx','vocab.txt'])files.push([DefaultConfig.mangaOcrRepo,file]);
  else if(ocr==='ppocrv5-korean')files.push(['https://huggingface.co/monkt/paddleocr-onnx/resolve/407d31ecdc555de8282c578889774861eea2667e/korean/korean_PP-OCRv5_mobile_rec.onnx','']);
  else if(ocr==='ppocrv6-manga'){const {PP_OCR_REC_URL}=await import('../lmt/ppocrv6.js');files.push([PP_OCR_REC_URL,''],['https://huggingface.co/Kellenok/PP-OCRv6_manga/resolve/62375557b5b0a4b2bc8e05484a97c7ea1df7229e/det/manga_det_v0.2.onnx','']);}
  else if(ocr==='pororo')files.push([DefaultConfig.pororoRepo,'brainocr.onnx'],[DefaultConfig.pororoRepo,'ocr-opt.txt']);
  else {const group=config.language==='Chinese (Simplified)'?'chinese':'latin';files.push([DefaultConfig.ocrRepo,DefaultConfig.ocrModelPath(group)],[DefaultConfig.ocrRepo,DefaultConfig.ocrDictPath(group)]);}
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
 if(local){
  const {ModelManager}=await import('@wllama/wllama/esm/index.js'),{cachedGguf}=await import('./model-gguf.js');
  const indexed=config.deviceTranslator==='index',catalog=indexed?await import('./index-models.js'):await import('./hymt-models.js'),model=(indexed?catalog.indexModel:catalog.hymtModel)(config.hymtQuant),url=(indexed?catalog.indexUrl:catalog.hymtUrl)(model);
  await cachedGguf(url,model,new ModelManager(),(message,value)=>status({loaded:0,total:0,...value,message}));count++;
 }
 return count;
}
