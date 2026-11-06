// Colour grading pass for the player: white balance (temperature, tint) and a 3D LUT
// from a .cube file. Runs in WebGL2 over the video or the upscaler canvas; saturation,
// contrast and brightness stay in the cheap CSS filter applied to the same layer.
import {useEffect,useRef,useState} from 'react';

export function parseCube(text,name=''){
 const lines=String(text).replace(/^﻿/,'').split(/\r?\n/);
 let size=0,title=name.replace(/\.cube$/i,''),min=[0,0,0],max=[1,1,1];const values=[];
 for(const raw of lines){
  const line=raw.trim();if(!line||line.startsWith('#'))continue;
  const parts=line.split(/\s+/);const key=parts[0].toUpperCase();
  if(key==='TITLE'){title=line.slice(5).trim().replace(/^"|"$/g,'')||title;continue;}
  if(key==='LUT_3D_SIZE'){size=Number(parts[1]);continue;}
  if(key==='LUT_1D_SIZE')throw Error('Нужен 3D LUT (.cube с LUT_3D_SIZE). Одномерные таблицы не поддерживаются.');
  if(key==='DOMAIN_MIN'){min=parts.slice(1,4).map(Number);continue;}
  if(key==='DOMAIN_MAX'){max=parts.slice(1,4).map(Number);continue;}
  if(/^[A-Z_]+$/.test(key))continue;
  if(parts.length>=3)values.push(Number(parts[0]),Number(parts[1]),Number(parts[2]));
 }
 if(!(size>=2&&size<=129))throw Error('В файле нет корректного LUT_3D_SIZE.');
 if(values.length!==size*size*size*3||values.some(v=>!Number.isFinite(v)))throw Error('Размер таблицы не совпадает с LUT_3D_SIZE.');
 const data=new Uint8Array(size*size*size*4);
 for(let i=0,j=0;i<values.length;i+=3,j+=4){
  for(let c=0;c<3;c++)data[j+c]=Math.round(Math.max(0,Math.min(1,(values[i+c]-min[c])/((max[c]-min[c])||1)))*255);
  data[j+3]=255;
 }
 return {size,data,title:title||'LUT'};
}

const VERTEX=`#version 300 es
in vec2 p;out vec2 uv;void main(){uv=vec2(p.x*.5+.5,.5-p.y*.5);gl_Position=vec4(p,0.,1.);}`;
const FRAGMENT=`#version 300 es
precision highp float;precision highp sampler3D;
uniform sampler2D source;uniform sampler3D lut;uniform float lutSize,amount,temperature,tint,sharpen;uniform bool hasLut,deband;uniform vec2 texel;
in vec2 uv;out vec4 color;
void main(){
 vec3 c=texture(source,uv).rgb;
 // Deband: where a neighbourhood is nearly flat, replace the pixel with a dithered average.
 if(deband){
  float n=fract(sin(dot(uv*1000.,vec2(12.9898,78.233)))*43758.5453);float a=n*6.2831853,r=10.+n*8.;
  vec2 o=vec2(cos(a),sin(a))*r*texel;vec3 avg=(texture(source,uv+o).rgb+texture(source,uv-o).rgb+texture(source,uv+vec2(-o.y,o.x)).rgb+texture(source,uv+vec2(o.y,-o.x)).rgb)*.25;
  vec3 diff=abs(avg-c);if(max(diff.r,max(diff.g,diff.b))<.018)c=avg+(n-.5)/255.;
 }
 // AMD FidelityFX CAS: contrast-adaptive sharpening.
 if(sharpen>0.){
  vec3 a=texture(source,uv+texel*vec2(-1,-1)).rgb,b=texture(source,uv+texel*vec2(0,-1)).rgb,cc=texture(source,uv+texel*vec2(1,-1)).rgb;
  vec3 d=texture(source,uv+texel*vec2(-1,0)).rgb,f=texture(source,uv+texel*vec2(1,0)).rgb;
  vec3 g=texture(source,uv+texel*vec2(-1,1)).rgb,h=texture(source,uv+texel*vec2(0,1)).rgb,i=texture(source,uv+texel*vec2(1,1)).rgb;
  vec3 mn=min(min(min(d,c),min(f,b)),h);mn+=min(mn,min(min(a,cc),min(g,i)));
  vec3 mx=max(max(max(d,c),max(f,b)),h);mx+=max(mx,max(max(a,cc),max(g,i)));
  vec3 amp=sqrt(clamp(min(mn,2.-mx)/max(mx,vec3(1e-4)),0.,1.));
  vec3 w=amp*(-1./mix(8.,5.,sharpen));c=clamp(((b+d+f+h)*w+c)/(1.+4.*w),0.,1.);
 }
 // Simple white balance: warm lifts red and lowers blue, tint trades green for magenta.
 c*=vec3(1.+temperature*.12-tint*.03,1.+tint*.08,1.-temperature*.12-tint*.03);
 c=clamp(c,0.,1.);
 if(hasLut){vec3 coord=c*((lutSize-1.)/lutSize)+.5/lutSize;c=mix(c,texture(lut,coord).rgb,amount);}
 color=vec4(c,1.);
}`;

function program(gl){
 const make=(type,src)=>{const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
 const p=gl.createProgram();gl.attachShader(p,make(gl.VERTEX_SHADER,VERTEX));gl.attachShader(p,make(gl.FRAGMENT_SHADER,FRAGMENT));gl.linkProgram(p);
 if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return p;
}

// Draws `source()` through the grade into `canvas` on every new frame until stopped.
export function startColorGrade(canvas,source,params,onError){
 const gl=canvas.getContext('webgl2',{premultipliedAlpha:false,preserveDrawingBuffer:true});
 if(!gl)throw Error('Браузер не поддерживает WebGL2, цветокоррекция LUT недоступна.');
 const prog=program(gl);gl.useProgram(prog);
 const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
 const loc=gl.getAttribLocation(prog,'p');gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
 const frame=gl.createTexture();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,frame);
 for(const [k,v] of [[gl.TEXTURE_MIN_FILTER,gl.LINEAR],[gl.TEXTURE_MAG_FILTER,gl.LINEAR],[gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE],[gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE]])gl.texParameteri(gl.TEXTURE_2D,k,v);
 const cube=gl.createTexture();gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_3D,cube);
 for(const [k,v] of [[gl.TEXTURE_MIN_FILTER,gl.LINEAR],[gl.TEXTURE_MAG_FILTER,gl.LINEAR],[gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE],[gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE],[gl.TEXTURE_WRAP_R,gl.CLAMP_TO_EDGE]])gl.texParameteri(gl.TEXTURE_3D,k,v);
 const u=name=>gl.getUniformLocation(prog,name);
 gl.uniform1i(u('source'),0);gl.uniform1i(u('lut'),1);
 let loadedLut=null,raf=0,stopped=false,last=-1,lastKey='';
 function draw(){
  raf=0;if(stopped)return;
  const src=source();if(!src){raf=requestAnimationFrame(draw);return;}
  const w=src.videoWidth||src.width,h=src.videoHeight||src.height;
  const p=params();const key=[p.temperature,p.tint,p.amount,p.lut?.title,p.sharpen,p.deband,w,h].join(':');
  const t=src.currentTime??performance.now();
  if(w&&h&&(src.tagName==='CANVAS'||t!==last||key!==lastKey)){
   if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
   gl.viewport(0,0,w,h);
   try{gl.activeTexture(gl.TEXTURE0);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,src);}catch(error){stop();onError?.(Error('Этот источник не разрешает обработку цвета на GPU.'));return;}
   if(p.lut!==loadedLut){loadedLut=p.lut;if(p.lut){gl.activeTexture(gl.TEXTURE1);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);gl.texImage3D(gl.TEXTURE_3D,0,gl.RGBA8,p.lut.size,p.lut.size,p.lut.size,0,gl.RGBA,gl.UNSIGNED_BYTE,p.lut.data);}}
   gl.uniform1f(u('lutSize'),p.lut?.size||2);gl.uniform1f(u('amount'),p.amount??1);gl.uniform1f(u('temperature'),p.temperature||0);gl.uniform1f(u('tint'),p.tint||0);gl.uniform1i(u('hasLut'),p.lut?1:0);gl.uniform1f(u('sharpen'),p.sharpen||0);gl.uniform1i(u('deband'),p.deband?1:0);gl.uniform2f(u('texel'),1/w,1/h);
   gl.drawArrays(gl.TRIANGLE_STRIP,0,4);last=t;lastKey=key;
  }
  raf=requestAnimationFrame(draw);
 }
 function stop(){stopped=true;cancelAnimationFrame(raf);}
 raf=requestAnimationFrame(draw);
 return stop;
}

const LUT_KEY='mv_video_lut',PRESET_KEY='mv_color_presets';
export function readCustomPresets(){try{return JSON.parse(localStorage.getItem(PRESET_KEY)||'[]');}catch{return [];}}
export function writeCustomPresets(list){try{localStorage.setItem(PRESET_KEY,JSON.stringify(list.slice(0,24)));}catch{}return list;}

// Keeps the loaded LUT (persisted when it fits in local storage) and runs the pass.
export function useColorGrade({canvasRef,videoRef,upscaledRef,upscaled,colors,onError}){
 const [lut,setLut]=useState(()=>{try{const saved=JSON.parse(localStorage.getItem(LUT_KEY)||'null');return saved?parseCube(saved.text,saved.name):null;}catch{return null;}});
 const [persisted,setPersisted]=useState(true);
 const params=useRef({});params.current={lut,amount:colors.lutAmount??1,temperature:colors.temperature||0,tint:colors.tint||0,sharpen:colors.sharpen||0,deband:!!colors.deband};
 const active=!!lut||!!colors.temperature||!!colors.tint||!!colors.sharpen||!!colors.deband;
 useEffect(()=>{
  const canvas=canvasRef.current;if(!active||!canvas)return;
  let stop;try{stop=startColorGrade(canvas,()=>upscaled?upscaledRef.current:videoRef.current,()=>params.current,onError);}catch(e){onError?.(e);}
  return()=>stop?.();
 },[active,upscaled]);
 async function load(file){
  const text=await file.text();const value=parseCube(text,file.name);setLut(value);
  try{localStorage.setItem(LUT_KEY,JSON.stringify({name:file.name,text}));setPersisted(true);}catch{setPersisted(false);}
  return value;
 }
 function clear(){setLut(null);try{localStorage.removeItem(LUT_KEY);}catch{}}
 return {lut,active,load,clear,persisted};
}
