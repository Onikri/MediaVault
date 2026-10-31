import {useEffect,useState} from 'react';
import {fetchCatalog,mergeCatalog,rankCatalog} from './catalog.js';
const remembered=new Map();
export const SEARCH_KINDS=[['all','Все'],['anime','Аниме'],['manga','Манга'],['ranobe','Ранобэ'],['book','Книги'],['music','Музыка'],['movie','Кино']];
const base=(kind,provider,id,title)=>({id:provider+':'+id,provider,providerId:String(id),kind,title,titles:{},aliases:[title],providers:[provider],genres:[],tags:[],links:[],ids:{},releases:[],cover:'',description:''});
export async function searchBooks(query,signal,fetcher=fetch){
 const r=await fetcher('https://openlibrary.org/search.json?'+new URLSearchParams({q:query,lang:'ru',limit:8,fields:'key,title,author_name,first_publish_year,cover_i,language'}),{signal:AbortSignal.any([signal,AbortSignal.timeout(10000)].filter(Boolean))});if(!r.ok)throw Error();const d=await r.json();return (d.docs||[]).filter(x=>x.title&&/^(?:\/?works\/)?OL\d+W$/.test(x.key)).map(x=>({...base('book','openlibrary',x.key,x.title),authors:x.author_name||[],year:x.first_publish_year||null,cover:x.cover_i?'https://covers.openlibrary.org/b/id/'+x.cover_i+'-L.jpg':'',sourceURL:'https://openlibrary.org/works/'+x.key.replace(/^(?:\/?works\/)?/,''),format:'Книга',description:(x.author_name||[]).join(', ')}));
}
export async function searchMusic(query,server,signal,fetcher=fetch){if(!server)return [];const r=await fetcher(server+'/music/search?'+new URLSearchParams({title:query}),{signal:AbortSignal.any([signal,AbortSignal.timeout(10000)].filter(Boolean))});if(!r.ok)throw Error();const d=await r.json();return (d.results||[]).filter(x=>/^[\w-]{11}$/.test(x.id||'')).slice(0,8).map(x=>({...base('music','youtube',x.id,x.title),youtubeId:x.id,artists:x.author?[x.author]:[],format:'Музыка',cover:x.thumbnail||'',description:x.author||''}));}
export function useGlobalSearch(query,kind,service,composing=false){
 const [state,setState]=useState({key:'',items:[],loading:false,failed:0}),text=query.trim(),key=[text,kind,service.server].join(':');
 useEffect(()=>{const abort=new AbortController();if(composing||text.length<2){setState({key,items:[],loading:false,failed:0});return()=>abort.abort();}const hit=remembered.get(key);if(hit&&hit.until>Date.now()){setState({key,items:hit.items,loading:false,failed:0});return()=>abort.abort();}setState({key,items:[],loading:true,failed:0});
  const timer=setTimeout(()=>{const scopes=kind==='all'?['anime','manga','book','music','movie']:kind==='movie'?['movie','tv']:[kind],jobs=[];
   const add=(label,work)=>jobs.push({label,work});
   for(const scope of scopes){if(scope==='book'){add('Open Library',()=>searchBooks(text,abort.signal));continue;}if(scope==='music'){add('Музыка',()=>searchMusic(text,service.server,abort.signal));continue;}
    const providers=['movie','tv'].includes(scope)?['tvmaze',...(service.server?['imdb']:[])]:['shikimori','anilist','jikan'];
    for(const provider of providers)add(provider,()=>fetchCatalog(provider,{query:text,kind:scope,server:service.server,signal:abort.signal,page:1}));
   }
   let remaining=jobs.length,failed=0;const groups=new Map(),publish=()=>{if(abort.signal.aborted)return;const items=rankCatalog(mergeCatalog([...groups.values()].flat()),text);setState({key,items,loading:remaining>0,failed});if(!remaining&&items.length){remembered.set(key,{items,until:Date.now()+120000});while(remembered.size>30)remembered.delete(remembered.keys().next().value);}};
   for(const [index,job] of jobs.entries())job.work().then(items=>groups.set(index,items)).catch(()=>failed++).finally(()=>{remaining--;publish();});if(!jobs.length)publish();
  },320);
  return()=>{clearTimeout(timer);abort.abort();};
 },[key,composing]);
 return state.key===key?state:{items:[],loading:text.length>=2&&!composing,failed:0};
}
