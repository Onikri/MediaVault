// Public catalogue identity only. Never persist stream URLs or account secrets.
const KEY='mv_public_titles_v1';
export function readOnlineTitle(hash=location.hash,storage=localStorage){
 const value=new URLSearchParams(hash.slice(1)).get('watch');if(!value)return null;
 const [kind,provider,...rest]=value.split(':'),id=rest.join(':');
 if(!['anime','manga','ranobe','book','movie','tv'].includes(kind)||!provider||!id||value.length>400)return null;
 const base={id:value,kind,provider,providerId:id,providers:[provider],title:'Загружаем тайтл…',ids:['shikimori','jikan'].includes(provider)?{mal:id}:{},genres:[],tags:[],aliases:[],titles:{},links:[],releases:[]};
 try{const saved=JSON.parse(storage.getItem(KEY)||'{}')[value];if(saved)return {...base,...saved,providers:saved.providers||[provider]};}catch{}
 if(kind==='anime'&&provider==='hentaichan-video'){
  try{
   const url=new URL(id.replace(/^hentaichan-video:/,''));
   if(url.protocol==='https:'&&!url.port&&!url.username&&!url.password&&['hentaichan.live','x3.h-chan.me','xxl.hentaichan.live','x17.h-chan.me'].includes(url.hostname)&&/^\/video\/(?:online\/)?\d+-[^/]+\.html$/i.test(url.pathname)){
    return {...base,title:'HentaiChan · Видео',age:18,adult:true,sourceOnly:true,sourceURL:url.href};
   }
  }catch{}
 }
 return base;
}
const LATIN={а:'a',б:'b',в:'v',г:'g',д:'d',е:'e',ё:'e',ж:'zh',з:'z',и:'i',й:'y',к:'k',л:'l',м:'m',н:'n',о:'o',п:'p',р:'r',с:'s',т:'t',у:'u',ф:'f',х:'h',ц:'ts',ч:'ch',ш:'sh',щ:'sch',ъ:'',ы:'y',ь:'',э:'e',ю:'yu',я:'ya',і:'i',ї:'yi',є:'ye',ґ:'g'};
export function titleSlug(title){
 return String(title||'').toLowerCase().replace(/[а-яёіїєґ]/g,c=>LATIN[c]??c).normalize('NFKD').replace(/[̀-ͯ]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,60).replace(/-+$/,'');
}
export function onlineTitleLocation(item,replace=false){
 const id=item.providerId||item.ids?.mal||item.id,provider=item.provider||'shikimori',key=[item.kind,provider,id].join(':');
 const snapshot=Object.fromEntries(['id','kind','provider','providers','providerId','title','titles','ids','aliases','cover','year','format','genres','tags','links','releases','sourceOnly','sourceUrl','sourceURL','age','adult','language'].map(k=>[k,item[k]]));
 if(item.kind==='manga')snapshot.catalogIds=[...new Set([item.catalogId,...(item.catalogIds||[]),...(item.sources||[]).map(source=>source.catalogId)].filter(id=>typeof id==='string'&&/^[a-f0-9]{32}$/.test(id)))].slice(0,100);
 try{const values=JSON.parse(localStorage.getItem(KEY)||'{}');delete values[key];values[key]={...snapshot,openedAt:Date.now()};localStorage.setItem(KEY,JSON.stringify(Object.fromEntries(Object.entries(values).slice(-40))));}catch{}
 // The same title keeps its open reader (#watch=…&read=N) across re-routing.
 const current=new URLSearchParams(location.hash.slice(1)),next=new URLSearchParams({watch:key});
 // A readable name in the address; the watch key alone identifies the title.
 const slug=titleSlug(item.titles?.ru||item.title);if(slug)next.set('name',slug);
 if(current.get('watch')===key&&/^\d{1,5}$/.test(current.get('read')||''))next.set('read',current.get('read'));
 const hash='#'+next;if(location.hash!==hash){history[replace?'replaceState':'pushState'](null,'',location.pathname+location.search+hash);dispatchEvent(new HashChangeEvent('hashchange'));}
}
