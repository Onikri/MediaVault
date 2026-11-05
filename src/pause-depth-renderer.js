// Paused-frame 2.5D: the captured frame is re-rendered with depth parallax
// (occlusion-aware UV offset), a background depth of field, a breathing
// depth shadow and a warm rim on near edges. Falls back to the shadow-only
// overlay until a frame texture is supplied.
export function depthRenderer(canvas,width,height){
 const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:false,antialias:false,depth:false,powerPreference:'low-power'});
 if(!gl)throw Error('Эффект глубины недоступен на этом устройстве.');
 const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw Error('Не удалось подготовить эффект глубины.');}return s;};
 const vertex=shader(gl.VERTEX_SHADER,'attribute vec2 p; varying vec2 uv; void main(){uv=vec2((p.x+1.0)*.5,(1.0-p.y)*.5);gl_Position=vec4(p,0,1);}');
 const fragment=shader(gl.FRAGMENT_SHADER,`precision mediump float; varying vec2 uv;
 uniform sampler2D depthTex; uniform sampler2D maskTex; uniform sampler2D frameTex;
 uniform vec2 texel; uniform vec2 frameTexel; uniform vec2 offset;
 uniform float cutoff; uniform float strength; uniform float focus; uniform float hasFrame;
 float depthAt(vec2 p){return texture2D(depthTex,p).r;}
 // Edge-preserving smoothing of the low-resolution depth map.
 float smoothDepth(vec2 p){float d=depthAt(p);float sum=d*.4;float w=.4;
  for(int i=0;i<4;i++){vec2 o=i==0?vec2(texel.x,0):i==1?vec2(-texel.x,0):i==2?vec2(0,texel.y):vec2(0,-texel.y);float n=depthAt(p+o);float k=.15*(1.0-smoothstep(.04,.15,abs(n-d)));sum+=n*k;w+=k;}
  return sum/w;}
 void main(){
  vec2 c=(uv-.5)/1.04+.5;
  // Near layers move more than far ones; three fixed-point steps keep a
  // near silhouette in front of the background it slides over.
  vec2 p=c;for(int i=0;i<3;i++){p=c-offset*(smoothDepth(p)-.42)*.045;}
  p=clamp(p,vec2(.001),vec2(.999));
  float d=smoothDepth(p);
  float t=smoothstep(cutoff-.209,cutoff+.209,d);float near=pow(t*t*(3.0-2.0*t),1.25);float far=1.0-near;
  float m=texture2D(maskTex,p).r*focus;
  if(hasFrame<.5){float shadow=far*strength*(1.0-m*.94);gl_FragColor=vec4(0.,0.,0.,shadow);return;}
  vec3 col=texture2D(frameTex,p).rgb;
  // Depth of field: a 12-tap disc whose radius grows with distance.
  float r=far*2.6;vec3 acc=col;
  for(int i=0;i<12;i++){float a=float(i)*.5236;vec2 o=vec2(cos(a),sin(a))*frameTexel*r*(i<6?1.6:3.2);acc+=texture2D(frameTex,p+o).rgb;}
  col=mix(col,acc/13.0,clamp(far*1.15,0.,1.));
  // Breathing depth shadow, softened where a character is focused.
  col*=1.0-far*strength*.62*(1.0-m*.9);
  // Warm rim on near edges (depth gradient).
  float gx=depthAt(p+vec2(texel.x*1.5,0))-depthAt(p-vec2(texel.x*1.5,0));float gy=depthAt(p+vec2(0,texel.y*1.5))-depthAt(p-vec2(0,texel.y*1.5));
  float rim=clamp(length(vec2(gx,gy))*5.0,0.,1.)*near;col+=vec3(1.0,.78,.67)*rim*.16;
  // Focused character: lift it, dim the rest.
  col=mix(col*(1.0-focus*.28),col*1.08+.015,m);
  float v=smoothstep(.98,.32,length((uv-.5)*vec2(1.0,.85)));col*=mix(.78,1.0,v);
  gl_FragColor=vec4(col,1.0);}`);
 const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Не удалось запустить эффект глубины.');
 gl.useProgram(program);const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
 const position=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
 const textures=[0,1,2].map(unit=>{const t=gl.createTexture();gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,t);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);return t;});
 const u=name=>gl.getUniformLocation(program,name);
 gl.uniform1i(u('depthTex'),0);gl.uniform1i(u('maskTex'),1);gl.uniform1i(u('frameTex'),2);gl.uniform2f(u('texel'),1/width,1/height);gl.uniform2f(u('frameTexel'),1/canvas.width,1/canvas.height);gl.uniform1f(u('hasFrame'),0);
 const cut=u('cutoff'),mix=u('strength'),focusUniform=u('focus'),offsetUniform=u('offset');
 const upload=(unit,data)=>{gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,textures[unit]);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);gl.texImage2D(gl.TEXTURE_2D,0,gl.LUMINANCE,width,height,0,gl.LUMINANCE,gl.UNSIGNED_BYTE,data);};
 upload(0,new Uint8Array(width*height));upload(1,new Uint8Array(width*height));
 let lastCutoff=-.24,lastStrength=.82,focus=0,target=0,lastMask=null,lastDraw=performance.now(),offset=[0,0];
 return {
  depth:data=>upload(0,data),
  frame(image){if(!image)return;try{gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D,textures[2]);gl.pixelStorei(gl.UNPACK_ALIGNMENT,4);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);gl.uniform2f(u('frameTexel'),1/(image.width||canvas.width),1/(image.height||canvas.height));gl.uniform1f(u('hasFrame'),1);}catch{gl.uniform1f(u('hasFrame'),0);}},
  parallax(x,y){offset=[Math.max(-1,Math.min(1,x)),Math.max(-1,Math.min(1,y))];},
  surface(data,{immediate=false}={}){target=data?1:0;if(data&&data!==lastMask){upload(1,data);lastMask=data;focus=0;}if(immediate)focus=target;},
  draw(cutoff=lastCutoff,strength=lastStrength){lastCutoff=cutoff;lastStrength=strength;const now=performance.now();focus+=(target-focus)*(1-Math.exp(-Math.max(0,now-lastDraw)/160));lastDraw=now;gl.viewport(0,0,canvas.width,canvas.height);gl.uniform1f(cut,cutoff);gl.uniform1f(mix,strength);gl.uniform1f(focusUniform,focus);gl.uniform2f(offsetUniform,offset[0],offset[1]);gl.drawArrays(gl.TRIANGLES,0,6);},
  dispose(){textures.forEach(t=>gl.deleteTexture(t));gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);}
 };
}
