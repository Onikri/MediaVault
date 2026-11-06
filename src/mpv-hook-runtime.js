// Runs mpv "user shader" hook files (fragment passes) in WebGL2. Used for Sirosky's
// Ani4K v2 and AniSD ArtCNN models (CC BY-NC 4.0, ArtCNN architecture MIT), which ship
// as LUMA doublers: video RGB -> luma -> network passes -> 2x luma + upscaled chroma -> RGB.
const SHADERS={
  'mpv-ani4kv2':()=>import('./vendor/mpv-shaders/Ani4Kv2_ArtCNN_C4F32_i2.glsl?raw'),
  'mpv-anisd':()=>import('./vendor/mpv-shaders/AniSD_ArtCNN_C4F32_i4.glsl?raw')
};
const INPUT_WIDTH={performance:960,balanced:1280,quality:1920};

export function parseHooks(text){
  const passes=[];let pass=null,inCode=false;
  for(const line of String(text).split(/\r?\n/)){
    const directive=line.match(/^\/\/!(\w+)\s*(.*)$/);
    if(directive){
      if(!pass||inCode){pass={binds:[],body:[],hook:'',save:'',width:'',height:'',desc:''};passes.push(pass);inCode=false;}
      const [,key,value]=directive;
      if(key==='BIND')pass.binds.push(value.trim());
      else if(key==='HOOK')pass.hook=value.trim();
      else if(key==='SAVE')pass.save=value.trim();
      else if(key==='WIDTH')pass.width=value.trim();
      else if(key==='HEIGHT')pass.height=value.trim();
      else if(key==='DESC')pass.desc=value.trim();
      else if(key==='COMPUTE')throw Error('Compute-шейдеры mpv здесь не поддерживаются.');
      continue;
    }
    if(pass){if(line.trim())inCode=true;pass.body.push(line);}
  }
  return passes.filter(p=>p.hook);
}
// mpv size expressions are reverse Polish: "LUMA.w 2.0 *".
export function evalSize(expr,sizes,fallback){
  if(!expr)return fallback;
  const stack=[];
  for(const token of expr.split(/\s+/)){
    const ref=token.match(/^(\w+)\.(w|h|width|height)$/);
    if(ref){const s=sizes[ref[1]];if(!s)throw Error('Нет текстуры '+ref[1]);stack.push(ref[2][0]==='w'?s.w:s.h);}
    else if(/^[-+*/<>]$/.test(token)){const b=stack.pop(),a=stack.pop();stack.push(token==='+'?a+b:token==='-'?a-b:token==='*'?a*b:token==='/'?a/b:token==='>'?Number(a>b):Number(a<b));}
    else stack.push(Number(token));
  }
  return Math.max(1,Math.round(stack.pop()));
}

const VERT=`#version 300 es
in vec2 p;out vec2 v_pos;void main(){v_pos=p*.5+.5;gl_Position=vec4(p,0.,1.);}`;
function passSource(pass){
  const names=[...new Set(pass.binds.map(b=>b==='HOOKED'?pass.hook:b))];
  const decl=names.map(n=>`uniform sampler2D ${n}_raw;uniform vec2 ${n}_size;
#define ${n}_pos v_pos
#define ${n}_pt (1.0/${n}_size)
#define ${n}_mul 1.0
#define ${n}_tex(p) texture(${n}_raw,(p))
#define ${n}_texOff(o) texture(${n}_raw,v_pos+(1.0/${n}_size)*vec2(o))`).join('\n');
  const hooked=`#define HOOKED_raw ${pass.hook}_raw
#define HOOKED_size ${pass.hook}_size
#define HOOKED_pos v_pos
#define HOOKED_pt (1.0/${pass.hook}_size)
#define HOOKED_tex(p) texture(${pass.hook}_raw,(p))
#define HOOKED_texOff(o) texture(${pass.hook}_raw,v_pos+(1.0/${pass.hook}_size)*vec2(o))`;
  return {names,src:`#version 300 es
precision highp float;precision highp int;
in vec2 v_pos;out vec4 mv_out;
${decl}
${names.includes(pass.hook)?hooked:''}
${pass.body.join('\n')}
void main(){mv_out=hook();}`};
}
const LUMA_FRAG=`#version 300 es
precision highp float;in vec2 v_pos;out vec4 o;uniform sampler2D src;
void main(){vec3 c=texture(src,v_pos).rgb;o=vec4(dot(c,vec3(.2126,.7152,.0722)),0.,0.,1.);}`;
// Network luma replaces Y; chroma comes from the bilinear-upscaled source.
const MERGE_FRAG=`#version 300 es
precision highp float;in vec2 v_pos;out vec4 o;uniform sampler2D luma,src;
void main(){vec3 c=texture(src,vec2(v_pos.x,1.-v_pos.y)).rgb;float y=dot(c,vec3(.2126,.7152,.0722));
float cb=(c.b-y)/1.8556,cr=(c.r-y)/1.5748;float Y=texture(luma,vec2(v_pos.x,1.-v_pos.y)).x;
o=vec4(clamp(vec3(Y+1.5748*cr,Y-.1873*cb-.4681*cr,Y+1.8556*cb),0.,1.),1.);}`;

function compile(gl,vs,fs){
  const sh=(t,s)=>{const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);if(!gl.getShaderParameter(x,gl.COMPILE_STATUS))throw Error('Шейдер не скомпилировался: '+gl.getShaderInfoLog(x));return x;};
  const p=gl.createProgram();gl.attachShader(p,sh(gl.VERTEX_SHADER,vs));gl.attachShader(p,sh(gl.FRAGMENT_SHADER,fs));gl.bindAttribLocation(p,0,'p');gl.linkProgram(p);
  if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return p;
}

export async function startMpvUpscaler(video,canvas,{profile,mode='balanced',onStats=()=>{},onFailure=()=>{}}={}){
  const load=SHADERS[profile];if(!load)throw Error('Неизвестный шейдер.');
  const text=(await load()).default,passes=parseHooks(text);
  if(video.readyState<2)await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('Нет кадра видео для улучшения.')),10000);video.addEventListener('loadeddata',()=>{clearTimeout(t);resolve();},{once:true});});
  const gl=canvas.getContext('webgl2',{alpha:false,antialias:false,powerPreference:'high-performance',preserveDrawingBuffer:false});
  if(!gl)throw Error('Нужен WebGL2.');
  if(!gl.getExtension('EXT_color_buffer_float'))throw Error('Видеокарта не поддерживает float-текстуры WebGL2.');
  const quad=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,quad);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);
  const lumaProgram=compile(gl,VERT,LUMA_FRAG),mergeProgram=compile(gl,VERT,MERGE_FRAG);
  const programs=passes.map(pass=>{const {names,src}=passSource(pass);const program=compile(gl,VERT,src);return {pass,names,program,uniforms:names.map(n=>[n,gl.getUniformLocation(program,n+'_raw'),gl.getUniformLocation(program,n+'_size')])};});
  const tex=(w,h,format,filter)=>{const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texStorage2D(gl.TEXTURE_2D,1,format,w,h);for(const [k,v] of [[gl.TEXTURE_MIN_FILTER,filter],[gl.TEXTURE_MAG_FILTER,filter],[gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE],[gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE]])gl.texParameteri(gl.TEXTURE_2D,k,v);return t;};
  const source=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,source);for(const [k,v] of [[gl.TEXTURE_MIN_FILTER,gl.LINEAR],[gl.TEXTURE_MAG_FILTER,gl.LINEAR],[gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE],[gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE]])gl.texParameteri(gl.TEXTURE_2D,k,v);
  const fbo=gl.createFramebuffer();let targets=new Map(),plan=null;
  const scaleCanvas=document.createElement('canvas'),scaleCtx=scaleCanvas.getContext('2d',{alpha:false});
  function layout(w,h){
    for(const t of targets.values())gl.deleteTexture(t.tex);targets=new Map();
    const sizes={LUMA:{w,h}};let luma={tex:tex(w,h,gl.RGBA16F,gl.NEAREST),w,h};
    const steps=programs.map(entry=>{
      const {pass}=entry,base=sizes[pass.hook];
      const w2=evalSize(pass.width,sizes,base.w),h2=evalSize(pass.height,sizes,base.h);
      const target={tex:tex(w2,h2,gl.RGBA16F,gl.NEAREST),w:w2,h:h2};
      if(pass.save)sizes[pass.save]={w:w2,h:h2};else sizes[pass.hook]={w:w2,h:h2};
      targets.set(entry,target);return {entry,target};
    });
    plan={w,h,luma,steps};canvas.width=sizes.LUMA.w;canvas.height=sizes.LUMA.h;
  }
  let stopped=false,frame=0,frames=0,since=performance.now(),last=-1;
  function draw(target,w,h){gl.bindFramebuffer(gl.FRAMEBUFFER,target?fbo:null);if(target)gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,target,0);gl.viewport(0,0,w,h);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);}
  function render(){
    if(stopped||video.readyState<2||video.currentTime===last)return;last=video.currentTime;
    const start=performance.now();
    const limit=INPUT_WIDTH[mode]||1280,vw=video.videoWidth,vh=video.videoHeight,w=Math.min(vw,limit),h=Math.round(w*vh/vw);
    if(!plan||plan.w!==w||plan.h!==h)layout(w,h);
    gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,source);
    if(w===vw)gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);
    else{scaleCanvas.width=w;scaleCanvas.height=h;scaleCtx.drawImage(video,0,0,w,h);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,scaleCanvas);}
    gl.useProgram(lumaProgram);gl.uniform1i(gl.getUniformLocation(lumaProgram,'src'),0);draw(plan.luma.tex,w,h);
    const live={LUMA:plan.luma};
    for(const {entry,target} of plan.steps){
      gl.useProgram(entry.program);
      entry.uniforms.forEach(([name,raw,size],i)=>{const t=live[name];gl.activeTexture(gl.TEXTURE0+i);gl.bindTexture(gl.TEXTURE_2D,t.tex);gl.uniform1i(raw,i);gl.uniform2f(size,t.w,t.h);});
      draw(target.tex,target.w,target.h);
      live[entry.pass.save||entry.pass.hook]=target;
    }
    gl.useProgram(mergeProgram);
    gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,live.LUMA.tex);gl.uniform1i(gl.getUniformLocation(mergeProgram,'luma'),0);
    gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,source);gl.uniform1i(gl.getUniformLocation(mergeProgram,'src'),1);
    draw(null,canvas.width,canvas.height);
    if(gl.isContextLost())throw Error('GPU освободил контекст.');
    canvas.style.opacity='1';frames++;
    const now=performance.now();if(now-since>1000){onStats({engine:profile,width:canvas.width,height:canvas.height,fps:Math.round(frames*1000/(now-since)),latency:Math.round(now-start)});frames=0;since=now;}
  }
  function tick(){frame=0;if(stopped)return;try{render();}catch(error){stop();onFailure(error);return;}frame=video.requestVideoFrameCallback?video.requestVideoFrameCallback(tick):requestAnimationFrame(tick);}
  const refresh=()=>{last=-1;try{render();}catch(error){stop();onFailure(error);}};
  function stop(){if(stopped)return;stopped=true;if(video.cancelVideoFrameCallback)video.cancelVideoFrameCallback(frame);else cancelAnimationFrame(frame);video.removeEventListener('seeked',refresh);video.removeEventListener('loadeddata',refresh);canvas.style.opacity='0';}
  video.addEventListener('seeked',refresh);video.addEventListener('loadeddata',refresh);
  tick();refresh();
  return stop;
}
