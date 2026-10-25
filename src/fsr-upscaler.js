// Two-pass AMD FSR1: edge-adaptive spatial reconstruction + RCAS sharpening.
// No temporal motion-vector requirement, neural weights or CPU pixel readbacks.
import {EASU,RCAS} from './fsr-shaders.js';
export function fsrSize(width,height,cap=2560){
 if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)throw Error('Некорректный размер видео.');
 const scale=Math.min(2,cap/width);return {width:Math.max(1,Math.round(width*scale)),height:Math.max(1,Math.round(height*scale))};
}
export async function startFsr(video,canvas,{mode='balanced',profile='fsr',onStats=()=>{},onFailure=()=>{}}={}){
 const gl=canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,powerPreference:'high-performance'});
 if(!gl)throw Error('FSR1 требует WebGL2. Включи аппаратное ускорение браузера.');
 const ext=gl.getExtension('WEBGL_debug_renderer_info'),renderer=String(gl.getParameter(ext?ext.UNMASKED_RENDERER_WEBGL:gl.RENDERER));
 const owned=[];const own=(type,value)=>{if(!value)throw Error('Недостаточно ресурсов GPU.');owned.push([type,value]);return value;};
 let stopped=false,callback=0,raf=0,width=0,height=0,lastTime=-1,frames=0,lastReport=performance.now(),wakeRef;
 function stop(){if(stopped)return;stopped=true;video.cancelVideoFrameCallback?.(callback);cancelAnimationFrame(raf);for(const e of ['play','seeked','loadeddata'])video.removeEventListener(e,wake);canvas.removeEventListener('webglcontextlost',lost);for(const [type,value]of owned.reverse())gl['delete'+type](value);canvas.style.opacity='0';}
 function lost(e){e.preventDefault();stop();onFailure(Error('GPU-контекст FSR освобождён. Можно включить его снова.'));}
 const vertex='#version 300 es\nin vec2 p;out vec2 uv;void main(){uv=p*.5+.5;gl_Position=vec4(p,0.,1.);}';
 function program(fragment){const p=own('Program',gl.createProgram());for(const [kind,source]of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]){const s=own('Shader',gl.createShader(kind));gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error('FSR: '+gl.getShaderInfoLog(s));gl.attachShader(p,s);}gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error('FSR: '+gl.getProgramInfoLog(p));return {p,position:gl.getAttribLocation(p,'p'),size:gl.getUniformLocation(p,'size'),image:gl.getUniformLocation(p,'image')};}
 try{
  const easu=program(EASU),rcas=program(RCAS),buffer=own('Buffer',gl.createBuffer()),input=own('Texture',gl.createTexture()),middle=own('Texture',gl.createTexture()),fbo=own('Framebuffer',gl.createFramebuffer());
  gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
  for(const t of [input,middle]){gl.bindTexture(gl.TEXTURE_2D,t);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);}
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
  function draw(pass,texture,w,h){gl.useProgram(pass.p);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.enableVertexAttribArray(pass.position);gl.vertexAttribPointer(pass.position,2,gl.FLOAT,false,0,0);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);gl.uniform1i(pass.image,0);gl.uniform2f(pass.size,w,h);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);}
  function render(){callback=raf=0;if(stopped)return;try{
   if(video.readyState>=2&&video.videoWidth&&!document.hidden&&lastTime!==video.currentTime){const started=performance.now();lastTime=video.currentTime;const next=fsrSize(video.videoWidth,video.videoHeight,mode==='performance'?1280:mode==='quality'?3840:2560);
    gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,input);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);
    if(width!==next.width||height!==next.height){width=canvas.width=next.width;height=canvas.height=next.height;gl.bindTexture(gl.TEXTURE_2D,middle);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,middle,0);if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('FSR: не удалось выделить промежуточный кадр.');}
    gl.viewport(0,0,width,height);gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);draw(easu,input,video.videoWidth,video.videoHeight);
    gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.useProgram(rcas.p);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,input);gl.uniform1i(gl.getUniformLocation(rcas.p,'original'),1);gl.uniform1f(gl.getUniformLocation(rcas.p,'sharpness'),profile==='fsr-soft'?1.5:.3);draw(rcas,middle,width,height);
    if(gl.isContextLost()||gl.getError()!==gl.NO_ERROR)throw Error('FSR: ошибка обработки кадра.');canvas.style.opacity='1';frames++;
    const now=performance.now();if(now-lastReport>=1000){onStats({renderer,software:/swiftshader|llvmpipe|software/i.test(renderer),width,height,fps:Math.round(frames*1000/(now-lastReport)),latency:Math.round(now-started)});lastReport=now;frames=0;}
   }
   if(video.requestVideoFrameCallback)callback=video.requestVideoFrameCallback(render);else if(!video.paused)raf=requestAnimationFrame(render);
  }catch(e){stop();onFailure(e);}}
  function wakeRender(){if(!stopped&&!callback&&!raf)render();}
  // Assign callbacks outside the setup scope so stop() can always remove them.
  wakeRef=wakeRender;canvas.addEventListener('webglcontextlost',lost);for(const e of ['play','seeked','loadeddata'])video.addEventListener(e,wake);render();return stop;
 }catch(e){stop();throw e;}
 function wake(){wakeRef?.();}
}
