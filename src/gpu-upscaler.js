// Spatial GPU enhancement, not neural / AI super-resolution.
// The decoded HTMLVideoElement remains the single source of audio and timing.
const VERT = `#version 300 es
in vec2 position;
out vec2 uv;
void main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}
`;
const FRAG = `#version 300 es
precision highp float;
uniform sampler2D image;
uniform vec2 texel;
uniform float sharpness;
in vec2 uv;
out vec4 color;
void main(){
  vec3 center=texture(image,uv).rgb;
  vec3 n=texture(image,uv+vec2(0.0,texel.y)).rgb;
  vec3 s=texture(image,uv-vec2(0.0,texel.y)).rgb;
  vec3 e=texture(image,uv+vec2(texel.x,0.0)).rgb;
  vec3 w=texture(image,uv-vec2(texel.x,0.0)).rgb;
  vec3 lo=min(center,min(min(n,s),min(e,w)));
  vec3 hi=max(center,max(max(n,s),max(e,w)));
  vec3 sharpened=center+(center*4.0-n-s-e-w)*sharpness;
  color=vec4(clamp(sharpened,lo,hi),1.0);
}
`;
function shader(gl,type,source) {
  const value=gl.createShader(type);
  gl.shaderSource(value,source); gl.compileShader(value);
  if(!gl.getShaderParameter(value,gl.COMPILE_STATUS)){
    const info=gl.getShaderInfoLog(value);gl.deleteShader(value);throw Error('Shader: '+info);
  }
  return value;
}
/**
 * GPU upload is throttled to video frames, and the backing buffer is capped
 * at 1080p to avoid high memory and power use on phones.
 */
export function startGpuUpscaler(video,canvas,{strength=0.14,onFailure=()=>{}}={}) {
  const gl=canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,
    preserveDrawingBuffer:false,powerPreference:'default'});
  if(!gl) throw Error('WebGL2 недоступен');
  const vertex=shader(gl,gl.VERTEX_SHADER,VERT),fragment=shader(gl,gl.FRAGMENT_SHADER,FRAG);
  const program=gl.createProgram();
  gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
  if(!gl.getProgramParameter(program,gl.LINK_STATUS)) throw Error('Ошибка GPU: '+gl.getProgramInfoLog(program));
  const buffer=gl.createBuffer(),texture=gl.createTexture();
  gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
  gl.useProgram(program);
  const location=gl.getAttribLocation(program,'position');
  gl.enableVertexAttribArray(location);
  gl.vertexAttribPointer(location,2,gl.FLOAT,false,0,0);
  gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  gl.uniform1i(gl.getUniformLocation(program,'image'),0);
  gl.uniform1f(gl.getUniformLocation(program,'sharpness'),Math.min(0.3,Math.max(0,Number(strength)||0)));
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
  const texel=gl.getUniformLocation(program,'texel');
  let stopped=false,scheduled=false,frameId=0,useVideoCallback=false;
  const resize=()=>{
    const rect=canvas.getBoundingClientRect();
    const ratio=Math.min(window.devicePixelRatio||1,2);
    const scale=Math.min(1,Math.sqrt(2073600/Math.max(1,rect.width*rect.height*ratio*ratio)));
    const width=Math.max(1,Math.round(rect.width*ratio*scale));
    const height=Math.max(1,Math.round(rect.height*ratio*scale));
    if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
    gl.viewport(0,0,width,height);
  };
  const fail=cause=>{if(stopped)return;stop();onFailure(cause);};
  const draw=()=>{
    if(stopped||document.hidden||video.readyState<2||!video.videoWidth)return;
    try{
      resize();
      gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);
      gl.uniform2f(texel,1/video.videoWidth,1/video.videoHeight);
      gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
      const problem=gl.getError();if(problem!==gl.NO_ERROR)throw Error('GPU WebGL error '+problem);
    }catch(cause){fail(cause);}
  };
  const loop=()=>{
    scheduled=false;
    if(stopped)return;
    draw();
    if(!video.paused&&!video.ended)schedule();
  };
  const schedule=()=>{
    if(stopped||scheduled||document.hidden)return;
    scheduled=true;
    useVideoCallback=typeof video.requestVideoFrameCallback==='function';
    frameId=useVideoCallback?video.requestVideoFrameCallback(loop):requestAnimationFrame(loop);
  };
  const refresh=()=>{draw();if(!video.paused)schedule();};
  const observer=typeof ResizeObserver==='function'?new ResizeObserver(refresh):null;
  observer?.observe(canvas);
  const visibility=()=>{if(!document.hidden)refresh();};
  const lost=event=>{event.preventDefault();fail(Error('Контекст GPU потерян'));};
  canvas.addEventListener('webglcontextlost',lost);
  video.addEventListener('play',schedule);
  video.addEventListener('seeked',refresh);
  video.addEventListener('loadeddata',refresh);
  document.addEventListener('visibilitychange',visibility);
  function stop(){
    if(stopped)return;stopped=true;
    if(scheduled){
      if(useVideoCallback)video.cancelVideoFrameCallback?.(frameId);
      else cancelAnimationFrame(frameId);
    }
    observer?.disconnect();
    canvas.removeEventListener('webglcontextlost',lost);
    video.removeEventListener('play',schedule);
    video.removeEventListener('seeked',refresh);
    video.removeEventListener('loadeddata',refresh);
    document.removeEventListener('visibilitychange',visibility);
    gl.deleteTexture(texture);gl.deleteBuffer(buffer);
    gl.deleteProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);
  }
  refresh();
  return stop;
}
