// A prefetched range archive keeps its signal in every lazy page reader.
// Transfer that signal's lifetime to the active reader before releasing prefetch.
export class ChapterLease{
 constructor(id,scope,load){this.id=id;this.scope=scope;this.controller=new AbortController();this.adopted=false;this.promise=load(this.controller.signal);this.promise.catch(()=>{});}
 matches(id,scope){return this.id===id&&this.scope===scope&&!this.closing&&!this.controller.signal.aborted;}
 adopt(signal){signal.throwIfAborted();this.controller.signal.throwIfAborted();this.adopted=true;this.parent=signal;this.cancel=()=>this.close();signal.addEventListener('abort',this.cancel,{once:true});return this.promise;}
 releasePrefetch(currentId){if(this.adopted)return;if(currentId!==this.id)this.close();else queueMicrotask(()=>{if(!this.adopted)this.close();});}
 // A background chapter save holds the lease so its lazy page readers keep
 // working after the reader closes; the last holder finishes the close.
 retain(){this.holds=(this.holds||0)+1;let released=false;return()=>{if(released)return;released=true;this.holds--;if(!this.holds&&this.closing)this.controller.abort();};}
 close(){if(this.parent&&this.cancel)this.parent.removeEventListener('abort',this.cancel);if(this.holds){this.closing=true;return;}this.controller.abort();}
}
