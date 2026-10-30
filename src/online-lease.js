export function onlineClientId(role='viewer',storage=globalThis.sessionStorage){
 let id;try{id=storage.getItem('mv-online-tab');if(!id){id=crypto.randomUUID();storage.setItem('mv-online-tab',id);}}catch{id=crypto.randomUUID();}
 return id+':'+role;
}
export function keepOnlineLease(service,token,onExpired=()=>{},events=globalThis){
 let closed=false,renewing=false,released=false;
 const release=()=>{if(released)return;released=true;service.request('/online/'+token,{method:'DELETE',keepalive:true}).catch(()=>{});};
 const renew=async()=>{if(closed||renewing)return;if(released){onExpired();return;}renewing=true;try{await service.request('/online/'+token+'/heartbeat',{method:'POST'});}catch(e){if(!closed&&e.status===410)onExpired();}finally{renewing=false;}};
 const pagehide=()=>release(),pageshow=()=>renew();
 const timer=setInterval(renew,30000);events.addEventListener('pagehide',pagehide);events.addEventListener('pageshow',pageshow);events.addEventListener('focus',pageshow);
 return()=>{closed=true;clearInterval(timer);events.removeEventListener('pagehide',pagehide);events.removeEventListener('pageshow',pageshow);events.removeEventListener('focus',pageshow);release();};
}
