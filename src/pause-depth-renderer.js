// DepthFX Studio's smooth depth cutoff/S-curve. No displaced UVs or RGB copy.
export function depthRenderer(canvas,width,height){
 const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:false,antialias:false,depth:false,powerPreference:'low-power'});
 if(!gl)throw Error('Эффект глубины недоступен на этом устройстве.');
 const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw Error('Не удалось подготовить эффект глубины.');}return s;};
 const vertex=shader(gl.VERTEX_SHADER,'attribute vec2 p; varying vec2 uv; void main(){uv=vec2((p.x+1.0)*.5,(1.0-p.y)*.5);gl_Position=vec4(p,0,1);}');
 const fragment=shader(gl.FRAGMENT_SHADER,`precision mediump float; varying vec2 uv; uniform sampler2D depthTex; uniform sampler2D maskTex; uniform vec2 texel; uniform float cutoff; uniform float strength; uniform float focus;
 void main(){float d=texture2D(depthTex,uv).r;float sum=d*.4;float weights=.4;
 vec2 offsets[4];offsets[0]=vec2(texel.x,0);offsets[1]=vec2(-texel.x,0);offsets[2]=vec2(0,texel.y);offsets[3]=vec2(0,-texel.y);
 for(int i=0;i<4;i++){float n=texture2D(depthTex,uv+offsets[i]).r;float w=.15*(1.0-smoothstep(.04,.15,abs(n-d)));sum+=n*w;weights+=w;}d=sum/weights;
 float t=smoothstep(cutoff-.209,cutoff+.209,d);float light=pow(t*t*(3.0-2.0*t),1.25);float shadow=(1.0-light)*strength;
 float m=texture2D(maskTex,uv).r*.5; m+=(texture2D(maskTex,uv+vec2(texel.x,0)).r+texture2D(maskTex,uv-vec2(texel.x,0)).r+texture2D(maskTex,uv+vec2(0,texel.y)).r+texture2D(maskTex,uv-vec2(0,texel.y)).r)*.125;
 m*=focus;shadow*=1.0-m*.85;float highlight=m*.035;float a=highlight+shadow*(1.0-highlight);
 vec3 rgb=vec3(1.0,.78,.67)*highlight/max(.001,a);gl_FragColor=vec4(rgb,a);}`);
 const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Не удалось запустить эффект глубины.');
 gl.useProgram(program);const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
 const position=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
 const textures=[0,1].map(unit=>{const t=gl.createTexture();gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,t);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);return t;});
 gl.uniform1i(gl.getUniformLocation(program,'depthTex'),0);gl.uniform1i(gl.getUniformLocation(program,'maskTex'),1);gl.uniform2f(gl.getUniformLocation(program,'texel'),1/width,1/height);
 const cut=gl.getUniformLocation(program,'cutoff'),mix=gl.getUniformLocation(program,'strength'),focusUniform=gl.getUniformLocation(program,'focus');
 const upload=(unit,data)=>{gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,textures[unit]);gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);gl.texImage2D(gl.TEXTURE_2D,0,gl.LUMINANCE,width,height,0,gl.LUMINANCE,gl.UNSIGNED_BYTE,data);};
 upload(0,new Uint8Array(width*height));upload(1,new Uint8Array(width*height));
 let lastCutoff=-.24,lastStrength=.82,focus=0,target=0,lastMask=null,lastDraw=performance.now();
 return {depth:data=>upload(0,data),surface(data,{immediate=false}={}){target=data?1:0;if(data&&data!==lastMask){upload(1,data);lastMask=data;focus=0;}if(immediate)focus=target;},draw(cutoff=lastCutoff,strength=lastStrength){lastCutoff=cutoff;lastStrength=strength;const now=performance.now();focus+=(target-focus)*(1-Math.exp(-Math.max(0,now-lastDraw)/160));lastDraw=now;gl.viewport(0,0,canvas.width,canvas.height);gl.uniform1f(cut,cutoff);gl.uniform1f(mix,strength);gl.uniform1f(focusUniform,focus);gl.drawArrays(gl.TRIANGLES,0,6);},dispose(){textures.forEach(t=>gl.deleteTexture(t));gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);}};
}
