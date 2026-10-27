// Incremental SSE framing, including split UTF-16 strings/escaped JSON content.
// Only public output is accumulated. Thought parts are counted, not displayed.
export function completedJsonRows(text){
 const begin=text.indexOf('[');if(begin<0)return 0;let depth=0,quoted=false,escaped=false,count=0;
 for(let i=begin;i<text.length;i++){
  const c=text[i];if(quoted){if(escaped)escaped=false;else if(c==='\\')escaped=true;else if(c==='"')quoted=false;continue;}
  if(c==='"'){quoted=true;continue;}if(c==='['||c==='{')depth++;if(c===']'||c==='}'){if(depth===2)count++;depth--;}
 }return count;
}
export function googleStreamAccumulator(onProgress=()=>{}){
 let buffer='',text='',chunks=0,thoughtChars=0,finishReason='',usageMetadata,promptFeedback,error;
 const accept=value=>{
  if(value.error){error=value.error;return;}
  chunks++;const candidate=value.candidates?.[0];
  for(const part of candidate?.content?.parts||[])if(part.thought)thoughtChars+=(part.text||'').length;else if(part.text)text+=part.text;
  if(text.length>1_000_000)throw Error('Поток Google превысил лимит размера.');
  if(candidate?.finishReason)finishReason=candidate.finishReason;if(value.usageMetadata)usageMetadata=value.usageMetadata;if(value.promptFeedback)promptFeedback=value.promptFeedback;
  onProgress({chunks,streamChars:text.length,thoughtChars,completedRegions:completedJsonRows(text)});
 };
 return {feed(chunk){
  buffer+=chunk;buffer=buffer.replaceAll('\r\n','\n');let at;
  while((at=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,at);buffer=buffer.slice(at+2);const data=block.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');if(data&&data!=='[DONE]')accept(JSON.parse(data));}
  if(buffer.length>2_000_000)throw Error('Событие Google превысило лимит размера.');
 },finish(raw){
  if(!chunks&&!error){if(!/^(?:data:|event:|:)/.test(raw.trimStart()))return JSON.parse(raw);this.feed(raw);}
  if(buffer.trim().startsWith('data:')){const data=buffer.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');if(data&&data!=='[DONE]')accept(JSON.parse(data));}
  return error?{error}:{candidates:[{finishReason:finishReason||undefined,content:{parts:[{text}]}}],usageMetadata,promptFeedback};
 }};
}
