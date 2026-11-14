export function onlineClientId(role='viewer',storage=globalThis.sessionStorage){
 let id;try{id=storage.getItem('mv-online-tab');if(!id){id=crypto.randomUUID();storage.setItem('mv-online-tab',id);}}catch{id=crypto.randomUUID();}
 return id+':'+role;
}
export function keepOnlineLease(service,token,onExpired=()=>{},events=globalThis){
 let closed=false,renewing=false,released=false,expired=false;
 const expire=()=>{if(!closed&&!expired){expired=true;onExpired();}};
 const release=()=>{if(released)return;released=true;service.request('/online/'+token,{method:'DELETE',keepalive:true}).catch(()=>{});};
 const renew=async()=>{if(closed||renewing||expired)return;if(released){expire();return;}renewing=true;try{const data=await service.request('/online/'+token+'/heartbeat',{method:'POST'});if(data?.expiresIn===0)expire();}catch(e){if([404,410].includes(e.status))expire();}finally{renewing=false;}};
 const pagehide=event=>{if(!event.persisted)release();},pageshow=()=>renew();
 const timer=setInterval(renew,30000);events.addEventListener('pagehide',pagehide);events.addEventListener('pageshow',pageshow);events.addEventListener('focus',pageshow);
 return()=>{closed=true;clearInterval(timer);events.removeEventListener('pagehide',pagehide);events.removeEventListener('pageshow',pageshow);events.removeEventListener('focus',pageshow);release();};
}
