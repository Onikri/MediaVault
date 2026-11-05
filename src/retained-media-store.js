// Only the live media tree and its capability stay in RAM. History contains no
// signed media URLs, cookies, decrypted images, keys or serialized React props.
export function createRetainedMediaStore(){
 const rows=new Map(),listeners=new Set();let active='',popup='',scope='guest',history=[],snapshot;
 function readHistory(){try{const value=JSON.parse(localStorage.getItem('mv_viewing_history_v1:'+scope)||'[]');history=Array.isArray(value)?value.filter(v=>v&&typeof v.id==='string'&&typeof v.label==='string'&&typeof v.route==='string'&&v.route.startsWith('#')).slice(0,40):[];}catch{history=[];}}
 function emit(){snapshot={rows:[...rows.values()],active,popup,history};for(const fn of listeners)fn();}
 function pause(row){row?.host?.querySelector('video.mv-player-media')?.pause();row?.host?.querySelector('[role=dialog]')?.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));}
 function remember(row){const item={id:row.id,label:row.label,kind:row.kind,route:row.route,at:Date.now(),...(row.resumeItemId?{resumeItemId:row.resumeItemId}:{})};history=[item,...history.filter(v=>v.id!==row.id)].slice(0,40);try{localStorage.setItem('mv_viewing_history_v1:'+scope,JSON.stringify(history));}catch{}}
 const store={rows,getSnapshot:()=>snapshot,subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},
  scope(value){value=value||'guest';if(value===scope)return;for(const [id,row] of rows){if((row.userId||'guest')!==value){pause(row);rows.delete(id);if(active===id)active='';if(popup===id)popup='';}}scope=value;readHistory();emit();},
  attach(id,descriptor,anchor,node){let row=rows.get(id);if(row){Object.assign(row,descriptor,{anchor,node});}else{row={...descriptor,id,anchor,node,playing:false,time:0};rows.set(id,row);}emit();},
  detach(id,anchor){const row=rows.get(id);if(!row||row.anchor!==anchor)return;row.anchor=null;if(active!==id)rows.delete(id);else if(popup!==id)pause(row);emit();},
  activate(id,descriptor={}){const row=rows.get(id);if(!row)return;const old=rows.get(active);if(old&&old.id!==id){pause(old);if(!old.anchor)rows.delete(old.id);}Object.assign(row,descriptor);active=id;remember(row);emit();},
  deactivate(id){if(active!==id)return;active='';if(popup===id)popup='';const row=rows.get(id);if(row&&!row.anchor)rows.delete(id);emit();},
  owner(id,stop){const row=rows.get(id);if(row)row.stop=stop;},
  media(id,change){const row=rows.get(id);if(!row)return;Object.assign(row,change);emit();},
  popup(id){if(active!==id)return;popup=popup===id?'':id;if(!popup&&!rows.get(id)?.anchor)pause(rows.get(id));emit();},
  return(id){const row=rows.get(id);if(!row)return;popup='';row.wantReturn=true;row.restore?.();if(!row.restore&&row.route){if(location.hash!==row.route)location.hash=row.route;else dispatchEvent(new HashChangeEvent('hashchange'));}emit();},
  close(id){const row=rows.get(id);if(!row)return;pause(row);active=active===id?'':active;popup=popup===id?'':popup;if(row.anchor&&row.stop)row.stop();else rows.delete(id);emit();},
  clear(){for(const row of rows.values())pause(row);rows.clear();active='';popup='';emit();},
  revisit(item){if(rows.has(item.id)&&active===item.id){store.return(item.id);return;}if(item.resumeItemId)dispatchEvent(new CustomEvent('mediavault:resume-item',{detail:{id:item.resumeItemId}}));else{if(location.hash!==item.route)location.hash=item.route;else dispatchEvent(new HashChangeEvent('hashchange'));}},
 };
 readHistory();emit();return store;
}
