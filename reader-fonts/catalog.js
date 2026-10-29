// SIL OFL 1.1 fonts are bundled locally; no Google Fonts requests.
export const MANGA_FONTS = [
 {id:'comic-relief',label:'Comic Relief · чёткий комикс',family:'MV Comic Relief',regular:new URL('./comic-relief.woff2',import.meta.url).href,bold:new URL('./comic-relief-bold.woff2',import.meta.url).href},
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
export async function loadMangaFont(id){
 const font=mangaFont(id);if(!font.regular)return mangaFontStack(id);
 if(!loaded.has(font.id)){
  const promise=Promise.all([[font.regular,'400'],...(font.bold?[[font.bold,'700']]:[])].map(async([url,weight])=>{const face=await new FontFace(font.family,`url("${url}")`,{weight,style:'normal'}).load();(globalThis.fonts||globalThis.document?.fonts).add(face);}));
  loaded.set(font.id,promise);promise.catch(()=>loaded.delete(font.id));
 }
 await loaded.get(font.id);return mangaFontStack(id);
}
