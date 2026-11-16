// Listening speed without touching the voice: WSOLA time-stretch of the PCM
// the voice already produced. The pitch, timbre and the Gemini 2.5 Flash
// native-audio voice itself stay exactly as synthesized; only the time between
// them shrinks. Short frames (30 ms, Hann window, half overlap) are taken from
// the input `speed` times faster than they are laid down; each frame is
// shifted by up to ±8 ms to the place where it continues the previous one most
// smoothly (cross-correlation), so no phase jumps are heard. At 1× the audio
// is passed through untouched, so saved audiobooks and the reference voice are
// never changed by this module.
//
// Streaming: push() takes the chunks as the server streams them and returns
// what can already be laid down; flush() returns the rest at the end.

export const SPEEDS=[.8,.9,1,1.1,1.2,1.3,1.5,1.75,2];
export const clampSpeed=value=>{const v=Number(value);return Number.isFinite(v)?Math.max(.5,Math.min(2.5,v)):1;};

export function createStretcher(sampleRate,speed){
 speed=clampSpeed(speed);
 if(speed===1)return {push:chunk=>chunk,flush:()=>new Float32Array(0),speed};
 const N=2*Math.max(64,Math.round(sampleRate*.015)),H=N/2,D=Math.max(16,Math.round(sampleRate*.008)),coarse=Math.max(1,Math.round(sampleRate/12000));
 // Periodic Hann: frames at half overlap sum to exactly one.
 const win=new Float32Array(N);for(let i=0;i<N;i++)win[i]=.5-.5*Math.cos(2*Math.PI*i/N);
 let input=new Float32Array(0),base=0,analysis=0,prev=-1,tail=new Float32Array(H),ended=false;
 const at=i=>{const k=i-base;return k>=0&&k<input.length?input[k]:0;};
 const available=()=>base+input.length;

 function frame(out){
  const nominal=Math.round(analysis);
  let best=nominal;
  if(prev>=0){
   // The natural continuation of the previous frame, matched over the overlap.
   const target=prev+H,lo=Math.max(0,nominal-D),hi=nominal+D;
   if(!ended&&Math.max(target+N,hi+N)>available())return false;
   // Coarse search over the window, then the exact offset around the best.
   const match=(d,step)=>{let sum=0,energy=1e-9;for(let i=0;i<H;i+=step){const x=at(d+i);sum+=x*at(target+i);energy+=x*x;}return sum/Math.sqrt(energy);};
   let score=-Infinity;
   for(let d=lo;d<=hi;d+=coarse){const value=match(d,coarse*2);if(value>score){score=value;best=d;}}
   const around=best;score=-Infinity;
   for(let d=Math.max(lo,around-coarse);d<=Math.min(hi,around+coarse);d++){const value=match(d,2);if(value>score){score=value;best=d;}}
  }else if(!ended&&nominal+N>available())return false;
  // At the end: no frame past the last input sample (only its fade-out tail).
  if(ended&&nominal>=available())return false;
  const piece=new Float32Array(H);
  for(let i=0;i<H;i++)piece[i]=tail[i]+at(best+i)*win[i];
  for(let i=0;i<H;i++)tail[i]=at(best+H+i)*win[H+i];
  out.push(piece);
  prev=best;analysis+=H*speed;
  // Input before what any later frame can read is dropped.
  const keep=Math.max(0,Math.min(prev+H,Math.round(analysis)-D)-base);
  if(keep>N*4){input=input.subarray(keep);base+=keep;}
  return true;
 }
 const join=parts=>{const all=new Float32Array(parts.reduce((n,p)=>n+p.length,0));let k=0;for(const p of parts){all.set(p,k);k+=p.length;}return all;};
 return {
  speed,
  push(chunk){
   if(ended||!chunk?.length)return new Float32Array(0);
   const grown=new Float32Array(input.length+chunk.length);grown.set(input);grown.set(chunk,input.length);input=grown;
   const out=[];while(frame(out));return join(out);
  },
  flush(){
   if(ended)return new Float32Array(0);
   ended=true;const out=[];while(frame(out));out.push(tail.slice());return join(out);
  },
 };
}

// A whole buffer at once (tests, previews).
export function stretch(audio,sampleRate,speed){
 const s=createStretcher(sampleRate,speed);if(s.speed===1)return audio;
 const head=s.push(audio),rest=s.flush(),all=new Float32Array(head.length+rest.length);all.set(head);all.set(rest,head.length);return all;
}
