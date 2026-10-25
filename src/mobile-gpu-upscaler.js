// Lightweight Catmull-Rom reconstruction and bounded luma sharpening in WebGL.
// Video frames go straight to a GPU texture; no Canvas getImageData / CPU NN.
export async function startMobileGpu(video,canvas,{mode='balanced',onStats=()=>{},onFailure=()=>{}}={}){
  const gl=canvas.getContext('webgl',{alpha:false,antialias:false,depth:false,stencil:false,preserveDrawingBuffer:false,powerPreference:'high-performance'});
  if(!gl)throw Error('WebGL недоступен. Включи аппаратное ускорение браузера или используй исходное видео.');
  const extension=gl.getExtension('WEBGL_debug_renderer_info');
  const renderer=extension?String(gl.getParameter(extension.UNMASKED_RENDERER_WEBGL)):String(gl.getParameter(gl.RENDERER));
  const software=/swiftshader|llvmpipe|software|microsoft basic render/i.test(renderer);
  const vertex='attribute vec2 p;varying vec2 uv;void main(){uv=p*.5+.5;gl_Position=vec4(p,0.,1.);}';
  const fragment=`precision highp float;varying vec2 uv;uniform sampler2D image;uniform vec2 size;uniform float strength;
vec4 cubic(float x){float x2=x*x;float x3=x2*x;return vec4(-.5*x+x2-.5*x3,1.-2.5*x2+1.5*x3,.5*x+2.*x2-1.5*x3,-.5*x2+.5*x3);}
vec3 sampleAt(vec2 p){return texture2D(image,clamp(p/size,vec2(.5)/size,(size-.5)/size)).rgb;}
void main(){vec2 pixel=uv*size-.5;vec2 f=fract(pixel);vec2 base=floor(pixel)+.5;vec4 wx=cubic(f.x);vec4 wy=cubic(f.y);vec3 c=vec3(0.);
for(int y=0;y<4;y++){for(int x=0;x<4;x++){c+=sampleAt(base+vec2(float(x-1),float(y-1)))*wx[x]*wy[y];}}
vec3 l=sampleAt(base+vec2(-1.,0.)),r=sampleAt(base+vec2(1.,0.)),t=sampleAt(base+vec2(0.,-1.)),b=sampleAt(base+vec2(0.,1.));vec3 center=sampleAt(base);vec3 lo=min(center,min(min(l,r),min(t,b))),hi=max(center,max(max(l,r),max(t,b)));c=clamp(c+(center-(l+r+t+b)*.25)*strength,lo-.015,hi+.015);gl_FragColor=vec4(clamp(c,0.,1.),1.);}`;
  const resources=[];
  const shader=(kind,text)=>{const s=gl.createShader(kind);resources.push(['shader',s]);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error('GPU не смог собрать мобильный фильтр.');return s;};
  const program=gl.createProgram();resources.push(['program',program]);
  try{gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('GPU не смог подключить мобильный фильтр.');}
  catch(error){for(const [kind,value]of resources)gl['delete'+kind[0].toUpperCase()+kind.slice(1)](value);throw error;}
  gl.useProgram(program);const buffer=gl.createBuffer(),texture=gl.createTexture();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);const location=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,2,gl.FLOAT,false,0,0);
  gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);gl.uniform1i(gl.getUniformLocation(program,'image'),0);gl.uniform1f(gl.getUniformLocation(program,'strength'),mode==='quality'?.22:.12);
  const size=gl.getUniformLocation(program,'size'),cap=mode==='performance'?960:mode==='quality'?1920:1440;
  let stopped=false,frame=0,raf=0,lastTime=-1,lastAt=0,frames=0,started=performance.now(),slow=0;
  function stop(){if(stopped)return;stopped=true;video.cancelVideoFrameCallback?.(frame);cancelAnimationFrame(raf);for(const event of ['play','seeked','loadeddata'])video.removeEventListener(event,wake);canvas.removeEventListener('webglcontextlost',lost);gl.deleteTexture(texture);gl.deleteBuffer(buffer);for(const [kind,value]of resources)gl['delete'+kind[0].toUpperCase()+kind.slice(1)](value);canvas.style.opacity='0';}
  function lost(event){event.preventDefault();stop();onFailure(Error('Контекст GPU был освобождён. Можно снова включить мобильный режим.'));}
  function tick(){frame=raf=0;if(stopped)return;
    if(video.readyState>=2&&!document.hidden&&video.currentTime!==lastTime&&performance.now()-lastAt>=1000/(mode==='performance'?24:30)){
      lastTime=video.currentTime;lastAt=performance.now();const start=lastAt;
      try{const width=Math.min(cap,video.videoWidth*2),height=Math.round(width*video.videoHeight/video.videoWidth);if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}gl.viewport(0,0,width,height);gl.uniform2f(size,video.videoWidth,video.videoHeight);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);if(gl.isContextLost()||gl.getError()!==gl.NO_ERROR)throw Error('Ошибка мобильного GPU-фильтра.');canvas.style.opacity='1';frames++;
        const latency=performance.now()-start;slow=latency>100?slow+1:Math.max(0,slow-1);if(slow>12)throw Error('Аппаратное ускорение не успевает. Попробуй экономный режим или исходное видео.');
        if(performance.now()-started>1000){onStats({engine:'Мобильный GPU',renderer,software,width,height,fps:Math.round(frames*1000/(performance.now()-started)),latency:Math.round(latency)});frames=0;started=performance.now();}
      }catch(error){stop();onFailure(error);return;}
    }
    if(video.requestVideoFrameCallback)frame=video.requestVideoFrameCallback(tick);else if(!video.paused)raf=requestAnimationFrame(tick);
  }
  function wake(){if(!stopped&&!frame&&!raf)tick();}
  canvas.addEventListener('webglcontextlost',lost);for(const event of ['play','seeked','loadeddata'])video.addEventListener(event,wake);tick();return stop;
}
