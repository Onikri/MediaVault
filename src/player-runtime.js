import {readProgress} from './playback-progress.js';
import {openingBounds} from './player-model.js';
export const PREF_KEY='mediavault_player_preferences_v1';
export const DEFAULTS={speed:1,volume:1,autoNext:false,autoSkip:false,gpu:false,upscaler:'auto',deviceProfile:'auto',neuralMode:'balanced',subSize:24,subOffset:8,depthShadow:true,depthModelAllowed:true,shadowStrength:.82,breathPeriod:10,breathAmplitude:.22,characterAuto:false,ambient:true,depthMode:'cinematic'};
export function getPrefs(){
  try{const saved=JSON.parse(localStorage.getItem(PREF_KEY)||'{}');return {...DEFAULTS,...saved,depthShadow:saved.depthShadow??saved.parallax??true};}catch{return DEFAULTS;}
}
export function clock(seconds){
  if(!Number.isFinite(seconds)||seconds<0)return '00:00';
  const n=Math.floor(seconds),h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;
  return (h?h+':'+String(m).padStart(2,'0'):String(m).padStart(2,'0'))+':'+String(s).padStart(2,'0');
}
export function keyFor(userId,libraryId,id){return [userId,libraryId,id];}
export function readResume(key){return readProgress(...key)?.time||0;}
export function openerKey(libraryId,id){return 'mediavault_opening_'+String(libraryId||'local')+'_'+id;}
export function getOpening(item,libraryId){
  try{
    const saved=localStorage.getItem(openerKey(libraryId,item.id));
    if(saved!==null)return openingBounds(JSON.parse(saved));
  }catch{}
  return openingBounds(item.opening||item.intro);
}
export const tracksOf=video=>Array.from(video?.textTracks||[]).map((track,index)=>({
  id:track.label==='Загруженные субтитры'?'local':'native:'+index,
  name:track.label||(track.language?track.language:'Дорожка '+(index+1))
}));
