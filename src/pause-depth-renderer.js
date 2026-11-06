// Paused-frame 2.5D. Inputs are prepared once per still: depth refined to the
// frame's resolution (pause-depth-refine.js), the frame and a pre-blurred copy.
// The near layer stays still while the background drifts behind it, gets a
// soft depth of field and the breathing depth shadow. No rings, no rim glow.
export function depthRenderer(canvas,width,height){
 const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:false,antialias:false,depth:false,powerPreference:'low-power'});
 if(!gl)throw Error('Эффект глубины недоступен на этом устройстве.');
 const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw Error('Не удалось подготовить эффект глубины.');}return s;};
 const vertex=shader(gl.VERTEX_SHADER,'attribute vec2 p; varying vec2 uv; void main(){uv=vec2((p.x+1.0)*.5,(1.0-p.y)*.5);gl_Position=vec4(p,0,1);}');
 const fragment=shader(gl.FRAGMENT_SHADER,`precision mediump float; varying vec2 uv;
 uniform sampler2D depthTex; uniform sampler2D maskTex; uniform sampler2D frameTex; uniform sampler2D blurTex;
 uniform vec2 offset; uniform float cutoff; uniform float strength; uniform float focus; uniform float hasFrame;
 float depthAt(vec2 p){return texture2D(depthTex,p).r;}
 void main(){
  // Slight zoom hides the edge the drift would otherwise reveal.
  vec2 c=(uv-.5)/1.025+.5;
  // Pivot on the near layer: characters stay put, the background moves.
  // Two fixed-point steps keep the silhouette in front of what slides behind.
  vec2 p=c;for(int i=0;i<2;i++){p=c+offset*(.78-depthAt(p))*.022;}
  p=clamp(p,vec2(.001),vec2(.999));
  float d=depthAt(p);
  float t=smoothstep(cutoff-.32,cutoff+.32,d);float near=t*t*(3.0-2.0*t);float far=1.0-near;
  float m=texture2D(maskTex,p).r*focus;
  if(hasFrame<.5){gl_FragColor=vec4(0.,0.,0.,far*strength*(1.0-m));return;}
  vec3 sharp=texture2D(frameTex,p).rgb,soft=texture2D(blurTex,p).rgb;
  // Depth of field only on the far layer, eased so mid-depth stays crisp.
  // Depth of field follows real depth only (the shadow breathes, focus does
  // not), so a character never drifts out of focus.
  vec3 col=mix(sharp,soft,(1.0-smoothstep(.2,.45,d))*.6);
  col*=1.0-far*strength*.38*(1.0-m);
  // Focus: keep the character as drawn, dim everything else a little.
  col*=1.0-focus*.22*(1.0-m);
  float v=smoothstep(1.0,.35,length((uv-.5)*vec2(1.0,.85)));col*=mix(.82,1.0,v);
  gl_FragColor=vec4(col,1.0);}`);
 const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Не удалось запустить эффект глубины.');
 gl.useProgram(program);const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
 const position=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
 const textures=[0,1,2,3].map(unit=>{const t=gl.createTexture();gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,t);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);return t;});
 const u=name=>gl.getUniformLocation(program,name);
 gl.uniform1i(u('depthTex'),0);gl.uniform1i(u('maskTex'),1);gl.uniform1i(u('frameTex'),2);gl.uniform1i(u('blurTex'),3);gl.uniform1f(u('hasFrame'),0);
 const cut=u('cutoff'),mix=u('strength'),focusUniform=u('focus'),offsetUniform=u('offset');
 const upload=(unit,data)=>{gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,textures[unit]);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);gl.texImage2D(gl.TEXTURE_2D,0,gl.LUMINANCE,width,height,0,gl.LUMINANCE,gl.UNSIGNED_BYTE,data);};
 const image=(unit,source)=>{gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,textures[unit]);gl.pixelStorei(gl.UNPACK_ALIGNMENT,4);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);};
 upload(0,new Uint8Array(width*height));upload(1,new Uint8Array(width*height));
 let lastCutoff=-.24,lastStrength=.82,focus=0,target=0,lastMask=null,lastDraw=performance.now(),offset=[0,0],hasBlur=false;
 return {
  depth:data=>upload(0,data),
  frame(source){if(!source)return;try{image(2,source);if(!hasBlur)image(3,source);gl.uniform1f(u('hasFrame'),1);}catch{gl.uniform1f(u('hasFrame'),0);}},
  blur(source){if(!source)return;try{image(3,source);hasBlur=true;}catch{}},
  parallax(x,y){offset=[Math.max(-1,Math.min(1,x)),Math.max(-1,Math.min(1,y))];},
  surface(data,{immediate=false}={}){target=data?1:0;if(data&&data!==lastMask){if(data.length===width*height)upload(1,data);lastMask=data;focus=0;}if(immediate)focus=target;},
  draw(cutoff=lastCutoff,strength=lastStrength){lastCutoff=cutoff;lastStrength=strength;const now=performance.now();focus+=(target-focus)*(1-Math.exp(-Math.max(0,now-lastDraw)/160));lastDraw=now;gl.viewport(0,0,canvas.width,canvas.height);gl.uniform1f(cut,cutoff);gl.uniform1f(mix,strength);gl.uniform1f(focusUniform,focus);gl.uniform2f(offsetUniform,offset[0],offset[1]);gl.drawArrays(gl.TRIANGLES,0,6);},
  dispose(){textures.forEach(t=>gl.deleteTexture(t));gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);}
 };
}
