// Real Supertonic 3 inference in the browser. Model files are served from the
// local benchmark copy by the test (same pinned bytes, SHA-256 checked).
import {startNarrationEngine,synthesize} from '/src/tts/engine.js';
window.runTts=async(prefer)=>{
 const loaded=await startNarrationEngine({prefer});
 const rows=[];
 for(const [lang,text] of [['ru','— Ты опять опоздал, — недовольно сказала Мирэй, скрестив руки на груди.'],['uk','Вітер приніс запах дощу, а десь удалині глухо прогримів грім.']]){
  const started=performance.now(),result=await synthesize({text,lang,voice:{F1:1},steps:5,speed:1});
  const seconds=result.audio.length/result.sampleRate,wall=(performance.now()-started)/1000;
  let peak=0;for(const v of result.audio)peak=Math.max(peak,Math.abs(v));
  rows.push({lang,seconds:+seconds.toFixed(2),wall:+wall.toFixed(2),rtf:+(wall/seconds).toFixed(3),peak:+peak.toFixed(3),provider:result.provider});
 }
 const blended=await synthesize({text:'Проверка смешанного голоса.',lang:'ru',voice:{F2:.6,M3:.4},steps:5});
 rows.push({blend:true,seconds:+(blended.audio.length/blended.sampleRate).toFixed(2)});
 return {provider:loaded.provider,rows};
};
