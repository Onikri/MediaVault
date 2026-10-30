// A visibility observer owns demand, not the lifetime of a decoded page.
// In particular, leaving the observer during cleanup must not revoke an image.
export class PageResource{
 constructor({create=blob=>URL.createObjectURL(blob),revoke=url=>URL.revokeObjectURL(url)}={}){Object.assign(this,{create,revoke});this.closed=false;this.source='';this.blob=null;this.pending=null;}
 async load(entry){
  if(this.closed)return null;
  if(this.source)return this;
  if(!this.pending)this.pending=Promise.resolve().then(()=>entry.async('blob')).then(blob=>{
   if(this.closed)return null;
   this.blob=blob;this.source=this.create(blob);return this;
  }).catch(error=>{this.pending=null;throw error;});
  return this.pending;
 }
 close(){this.closed=true;if(this.source)this.revoke(this.source);this.source='';this.blob=null;}
}
