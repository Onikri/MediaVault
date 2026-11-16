// Listening speed (WSOLA): real signal processing on synthetic tones, no mocks.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createStretcher,stretch,clampSpeed} from '../src/tts/stretch.js';

const tone=(rate,seconds,freq)=>Float32Array.from({length:Math.round(rate*seconds)},(_,i)=>.5*Math.sin(2*Math.PI*freq*i/rate));
// Dominant frequency by zero crossings over the steady middle of the signal.
function pitch(audio,rate){
 const from=Math.floor(audio.length*.2),to=Math.floor(audio.length*.8);let crossings=0;
 for(let i=from+1;i<to;i++)if((audio[i-1]<0)!==(audio[i]<0))crossings++;
 return crossings/2/((to-from)/rate);
}
const rms=(audio,from,to)=>Math.sqrt(audio.subarray(from,to).reduce((s,x)=>s+x*x,0)/(to-from));

test('1× passes the voice through untouched',()=>{
 const audio=tone(24000,.5,220);
 assert.equal(stretch(audio,24000,1),audio);
 const s=createStretcher(24000,1),chunk=audio.subarray(0,100);
 assert.equal(s.push(chunk),chunk);assert.equal(s.flush().length,0);
});

test('faster and slower speech keeps its pitch and changes only its length',()=>{
 for(const rate of [24000,44100])for(const speed of [.8,1.25,1.5,2]){
  const audio=tone(rate,2,180),out=stretch(audio,rate,speed);
  const expected=audio.length/speed;
  assert.ok(Math.abs(out.length-expected)<rate*.05,`${rate} Hz ${speed}×: ${out.length} vs ${Math.round(expected)}`);
  assert.ok(Math.abs(pitch(out,rate)-180)<4,`${rate} Hz ${speed}×: pitch ${pitch(out,rate).toFixed(1)}`);
  // No dips or clicks at frame joins: the level stays that of the tone.
  const mid=Math.floor(out.length/2),level=rms(out,mid-2000,mid+2000);
  assert.ok(Math.abs(level-.5/Math.SQRT2)<.04,`${speed}× level ${level.toFixed(3)}`);
 }
});

test('streamed chunks give the same audio as the whole clip',()=>{
 const rate=24000,audio=tone(rate,1.2,240),whole=stretch(audio,rate,1.5);
 const s=createStretcher(rate,1.5),parts=[];
 for(let i=0;i<audio.length;i+=777)parts.push(s.push(audio.subarray(i,i+777)));
 parts.push(s.flush());
 const joined=new Float32Array(parts.reduce((n,p)=>n+p.length,0));let k=0;for(const p of parts){joined.set(p,k);k+=p.length;}
 assert.equal(joined.length,whole.length);
 let diff=0;for(let i=0;i<whole.length;i++)diff=Math.max(diff,Math.abs(joined[i]-whole[i]));
 assert.ok(diff<1e-6,'max difference '+diff);
});

test('speed values are clamped to what still sounds like speech',()=>{
 assert.equal(clampSpeed('x'),1);assert.equal(clampSpeed(9),2.5);assert.equal(clampSpeed(.1),.5);assert.equal(clampSpeed(1.3),1.3);
});

test('the old voice «pace» becomes the listening speed and never reaches the Gemini direction',async()=>{
 const {cleanPrefs}=await import('../src/tts/chapter-script.js');
 const {geminiRows}=await import('../src/tts/gemini-voice.js');
 assert.equal(cleanPrefs({pace:1.35}).speed,1.3,'snapped to an offered speed');
 assert.equal(cleanPrefs({pace:1.2,speed:1}).speed,1,'an explicit speed wins');
 assert.equal(cleanPrefs({}).speed,1);
 const segments=[{id:0,p:0,kind:'narration',text:'Ночь опустилась на город.'},{id:1,p:1,kind:'speech',speaker:'Мирэй',gender:'f',text:'Ты опять опоздал!'}];
 const rows=geminiRows(segments,{cast:{Мирэй:{gender:'f'}},voices:{Мирэй:'Zephyr'},narrator:'Charon',bible:null});
 for(const row of rows)assert.doesNotMatch(row.style,/темп/,'the voice is asked for its own tempo: '+row.style);
});
