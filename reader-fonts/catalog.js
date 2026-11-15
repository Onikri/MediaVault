// SIL OFL 1.1 fonts are bundled locally; no Google Fonts requests.
export const MANGA_FONTS = [
 {id:'comic-relief',label:'Comic Relief · чёткий комикс',family:'MV Comic Relief',regular:new URL('./comic-relief.woff2',import.meta.url).href,bold:new URL('./comic-relief-bold.woff2',import.meta.url).href},
 {id:'balsamiq-sans',label:'Balsamiq Sans · плотный комикс',family:'MV Balsamiq Sans',regular:new URL('./balsamiq-sans.woff2',import.meta.url).href,bold:new URL('./balsamiq-sans-bold.woff2',import.meta.url).href},
 {id:'caveat',label:'Caveat · живые пометки',family:'MV Caveat',regular:new URL('./caveat.woff2',import.meta.url).href},
 {id:'pangolin',label:'Pangolin · мягкий рукописный',family:'MV Pangolin',regular:new URL('./pangolin.woff2',import.meta.url).href},
 {id:'neucha',label:'Neucha · узкий рукописный',family:'MV Neucha',regular:new URL('./neucha.woff2',import.meta.url).href},
 {id:'ruslan-display',label:'Ruslan Display · крик и спецэффекты',family:'MV Ruslan Display',regular:new URL('./ruslan-display.woff2',import.meta.url).href},
 {id:'marck-script',label:'Marck Script · записки и рукопись',family:'MV Marck Script',regular:new URL('./marck-script.woff2',import.meta.url).href},
 {id:'press-start',label:'Press Start 2P · игровые сообщения',family:'MV Press Start',regular:new URL('./press-start.woff2',import.meta.url).href},
 {id:'pt-serif',label:'PT Serif · повествование',family:'MV PT Serif',regular:new URL('./pt-serif.woff2',import.meta.url).href},
 {id:'system',label:'Системный · нейтральный',family:'system-ui'},
];
export function mangaFont(id){return MANGA_FONTS.find(f=>f.id===id)||MANGA_FONTS[0];}
export function mangaFontStack(id){const font=mangaFont(id);return font.id==='system'?'system-ui, sans-serif':`"${font.family}", system-ui, sans-serif`;}
const loaded=new Map();
// A source is a URL or the font bytes (ArrayBuffer); works in windows and workers.
function loadFaces(key,family,sources){
 if(!loaded.has(key)){
  const promise=Promise.all(sources.map(async([source,weight])=>{const face=await new FontFace(family,typeof source==='string'?`url("${source}")`:source,{weight,style:'normal'}).load();(typeof globalThis.fonts?.add==='function'?globalThis.fonts:globalThis.document?.fonts).add(face);}));
  loaded.set(key,promise);promise.catch(()=>loaded.delete(key));
 }
 return loaded.get(key);
}
export async function loadMangaFont(id){
 const font=mangaFont(id);if(!font.regular)return mangaFontStack(id);
 await loadFaces(font.id,font.family,[[font.regular,'400'],...(font.bold?[[font.bold,'700']]:[])]);return mangaFontStack(id);
}

// Situational typefaces. The main typeface carries speech, thoughts (italic)
// and shouts; a separate face is used only for narration boxes, small side
// chatter, sound effects and handwritten notes.
// Private fonts are the owner's own licensed files. They are never part of
// this repository or the public site bundle: a local build picks them up from
// the gitignored reader-fonts/local/, the deployed site receives them from the
// owner's server after owner authentication (registerPrivateFonts). Each file
// is assigned to a role by its name.
const PRIVATE_ROLES=[[/beatdown|smash|hictor/i,'sfx-loud'],[/noisy|jinkies|hitch/i,'sfx'],[/kunkel/i,'chatter'],[/leo.?hand/i,'note'],[/guest/i,'note'],[/diamond/i,'note']];
const privateFonts=[];
function addPrivate(file,source){
 const name=String(file).split('/').pop().replace(/\.[^.]+$/,''),order=PRIVATE_ROLES.findIndex(([pattern])=>pattern.test(name));
 if(order<0||privateFonts.some(f=>f.name===name))return;
 privateFonts.push({name,id:'private:'+name,family:'MV Private '+name.replace(/[^\w ]/g,' '),source,role:PRIVATE_ROLES[order][1],order});privateFonts.sort((a,b)=>a.order-b.order);
}
try{for(const [path,url]of Object.entries(import.meta.glob('./local/*.{otf,ttf,woff2,OTF,TTF,WOFF2}',{eager:true,query:'?url',import:'default'})))addPrivate(path,url);}catch{}
// fonts: [{name, data: ArrayBuffer | URL string}]
export function registerPrivateFonts(fonts){for(const font of fonts||[])if(font?.name&&font.data)addPrivate(font.name,font.data);return privateFonts.length;}
export const privateFontIds=()=>privateFonts.map(f=>f.id);
// A private face for sfx / chatter / note, or null when the owner supplied none.
export async function loadPrivateFace(role,{loud=1,fallback='system-ui, sans-serif'}={}){
 const wanted=role==='sfx'?(loud>=1.2?['sfx-loud','sfx']:['sfx','sfx-loud']):[role];
 for(const key of wanted)for(const font of privateFonts.filter(f=>f.role===key)){
  try{await loadFaces(font.id,font.family,[[font.source,'400']]);return {id:font.id,stack:`"${font.family}", ${fallback}`,weight:400,italic:false,upper:role==='sfx'};}catch{}
 }
 return null;
}
const FALLBACK={narration:main=>main==='pangolin'?'comic-relief':'pangolin',chatter:main=>main==='neucha'?'pangolin':'neucha',note:main=>main==='neucha'?'pangolin':'neucha',sfx:()=>'ruslan-display'};
// Resolves the face for a typesetting role: {id, stack, weight, italic, upper}.
export async function loadRoleFace(role,main='comic-relief',{loud=1}={}){
 if(role==='speech'||role==='thought')return {id:mangaFont(main).id,stack:await loadMangaFont(main),weight:400,italic:role==='thought'};
 const own=await loadPrivateFace(role,{loud,fallback:await loadMangaFont(main)});if(own)return own;
 const id=(FALLBACK[role]||(()=>main))(mangaFont(main).id);return {id,stack:await loadMangaFont(id),weight:400,italic:false,upper:role==='sfx'};
}
