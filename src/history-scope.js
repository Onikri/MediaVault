// History belongs to a profile: every signed-in user (and the guest) keeps
// their own list of opened titles on this device.
const OPENS='mv_title_opens_v1:',LEGACY='mv_public_titles_v1',MOVED='mv_title_opens_moved_v1';
let scope='guest';
export const historyScope=()=>scope;
function read(key,fallback){try{return JSON.parse(localStorage.getItem(key)||'null')??fallback;}catch{return fallback;}}
export function setHistoryScope(value){
 const previous=scope;scope=value?String(value):'guest';
 // Opens recorded before profiles had their own history go to the first
 // signed-in profile that opens the site on this device, once.
 if(scope!=='guest'&&!localStorage.getItem(MOVED)){
  const legacy=read(LEGACY,{}),opens=read(OPENS+scope,{});
  for(const [key,value] of Object.entries(legacy))if(value?.openedAt&&!opens[key])opens[key]=value.openedAt;
  try{localStorage.setItem(OPENS+scope,JSON.stringify(opens));localStorage.setItem(MOVED,scope);}catch{}
 }
 // What was opened before signing in belongs to the person who signs in.
 if(previous==='guest'&&scope!=='guest'){
  const guest=read(OPENS+'guest',{});
  if(Object.keys(guest).length){const opens={...read(OPENS+scope,{}),...guest};try{localStorage.setItem(OPENS+scope,JSON.stringify(Object.fromEntries(Object.entries(opens).sort((a,b)=>a[1]-b[1]).slice(-60))));localStorage.removeItem(OPENS+'guest');}catch{}}
 }
 dispatchEvent(new Event('mediavault-history-scope'));
}
const who=user=>user?String(user):scope;
export function titleOpens(user){return read(OPENS+who(user),{});}
export function rememberTitleOpen(key){
 const opens=titleOpens();delete opens[key];opens[key]=Date.now();
 try{localStorage.setItem(OPENS+scope,JSON.stringify(Object.fromEntries(Object.entries(opens).slice(-60))));}catch{}
}
export const scopedKey=(base,user)=>base+':'+who(user);
