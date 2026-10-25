const KEY='mediavault_privacy_v1';
const fallback={version:1,chosen:false,remember:false};
export function privacyPreferences(){try{return {...fallback,...JSON.parse(localStorage.getItem(KEY)||'{}')};}catch{return {...fallback};}}
export function savePrivacyPreferences(remember){
  const value={version:1,chosen:true,remember:!!remember,updatedAt:Date.now()};
  try{localStorage.setItem(KEY,JSON.stringify(value));}catch{}
  // Preferences only. No identity, Google token, phrase or vault key in cookies.
  const path=new URL(import.meta.env?.BASE_URL||'./',location.href).pathname;
  document.cookie='mv_preferences='+encodeURIComponent(JSON.stringify({v:1,remember:!!remember}))+'; Max-Age=31536000; Path='+path+'; SameSite=Strict'+(location.protocol==='https:'?'; Secure':'');
  window.dispatchEvent(new CustomEvent('mediavault-privacy',{detail:value}));return value;
}
