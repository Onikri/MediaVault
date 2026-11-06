// Public catalogue identity only. Never persist stream URLs or account secrets.
const KEY='mv_public_titles_v1';
export function readOnlineTitle(hash=location.hash,storage=localStorage){
 const value=new URLSearchParams(hash.slice(1)).get('watch');if(!value)return null;
 const [kind,provider,...rest]=value.split(':'),id=rest.join(':');
 if(!['anime','manga','ranobe','book','movie','tv'].includes(kind)||!provider||!id||value.length>400)return null;
 const base={id:value,kind,provider,providerId:id,providers:[provider],title:'Загружаем тайтл…',ids:['shikimori','jikan'].includes(provider)?{mal:id}:{},genres:[],tags:[],aliases:[],titles:{},links:[],releases:[]};
 try{const saved=JSON.parse(storage.getItem(KEY)||'{}')[value];if(saved)return {...base,...saved,providers:saved.providers||[provider]};}catch{}
 if(kind==='manga'&&provider==='hitomi'&&/^hitomi:\d{1,10}$/.test(id)){
  return {...base,title:'Hitomi',age:18,adult:true,sourceOnly:true,sourceURL:'https://hitomi.la/reader/'+id.slice(7)+'.html'};
 }
 if(kind==='manga'&&provider==='hentaichan-cc'&&/^hentaichan-cc:[\w-]{1,240}$/.test(id)){
  return {...base,title:'HentaiChan.cc',age:18,adult:true,sourceOnly:true,sourceURL:'https://hentaichan.cc/manga/'+id.slice(14)};
 }
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
export function onlineTitleLocation(item,replace=false){
 const id=item.providerId||item.ids?.mal||item.id,provider=item.provider||'shikimori',key=[item.kind,provider,id].join(':');
 const snapshot=Object.fromEntries(['id','kind','provider','providers','providerId','title','titles','ids','aliases','cover','year','format','genres','tags','links','releases','sourceOnly','sourceUrl','sourceURL','age','adult','language'].map(k=>[k,item[k]]));
 try{const values=JSON.parse(localStorage.getItem(KEY)||'{}');delete values[key];values[key]=snapshot;localStorage.setItem(KEY,JSON.stringify(Object.fromEntries(Object.entries(values).slice(-40))));}catch{}
 const hash='#'+new URLSearchParams({watch:key});if(location.hash!==hash){history[replace?'replaceState':'pushState'](null,'',location.pathname+location.search+hash);dispatchEvent(new HashChangeEvent('hashchange'));}
}
