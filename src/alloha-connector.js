const storageKey='mediavault_alloha_connector';
export const ALLOHA_MODE_VERSION=64;
export function isAllohaUrl(value){
 try{
  const {protocol,hostname}=new URL(value);
  return protocol==='https:'&&(hostname==='alloha.yani.tv'||/\.(?:stravers\.live|thealloha\.club|alloha\.tv)$/.test(hostname));
 }catch{return false;}
}
export function allohaMode(){
 try{return localStorage.getItem(storageKey)==='bnsi'?'bnsi':'browser';}catch{return 'browser';}
}
export function setAllohaMode(mode){
 localStorage.setItem(storageKey,mode==='browser'?'browser':'bnsi');
}
export function allohaRequest(path,options,serverVersion){
 const body=options?.body;
 if(!(Number(serverVersion)>=ALLOHA_MODE_VERSION)||!body||!isAllohaUrl(body.url)
  ||body.kind!=='video'||!['/online/prepare','/online/exports'].includes(path))return options;
 return {...options,body:{...body,allohaMode:body.allohaMode??allohaMode()}};
}
export function allohaJob(job,serverVersion){
 if(!(Number(serverVersion)>=ALLOHA_MODE_VERSION)||job.version<2
  ||!['video','anime'].includes(job.section||'anime'))return job;
 return {...job,alloha_mode:job.alloha_mode??allohaMode()};
}
