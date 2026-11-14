import {useEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ExternalLink,ImageIcon,LoaderCircle,Search,X} from 'lucide-react';
import {findArtTags,loadArts} from './art-source.js';
import './art-wall.css';

// «Фото»: a pinboard of fan art for a character or a series. Pictures come
// straight from Danbooru's public API, general rating only, nothing cached.
export default function ArtWall({initialQuery='',initialTitle=''}){
 const reduce=useReducedMotion(),[query,setQuery]=useState(initialQuery),[tags,setTags]=useState([]),[tag,setTag]=useState(null);
 const [posts,setPosts]=useState([]),[page,setPage]=useState(1),[busy,setBusy]=useState(false),[done,setDone]=useState(false),[error,setError]=useState(''),[open,setOpen]=useState(null);
 const sentinel=useRef(null),abort=useRef(null);
 async function resolve(text,{auto=false}={}){
  const value=text.trim();if(!value)return;
  abort.current?.abort();const controller=new AbortController();abort.current=controller;
  setBusy(true);setError('');setTags([]);
  try{
   const found=await findArtTags(value,{signal:controller.signal,hint:initialTitle});
   if(controller.signal.aborted)return;
   setTags(found);
   if(!found.length){setTag(null);setPosts([]);setDone(true);setError(/[а-яё]/i.test(value)?'Арты подписаны латиницей — попробуй имя так, как его пишут на английском.':'Не нашли такого персонажа или тайтла.');}
   else if(auto||found.length)pick(found[0]);
  }catch(e){if(!controller.signal.aborted)setError('Сервис артов сейчас не отвечает. Попробуй позже.');}
  finally{if(!controller.signal.aborted)setBusy(false);}
 }
 function pick(value){setTag(value);setPosts([]);setPage(1);setDone(false);}
 useEffect(()=>{if(initialQuery)resolve(initialQuery,{auto:true});return()=>abort.current?.abort();},[initialQuery]);
 useEffect(()=>{
  if(!tag||done)return;const controller=new AbortController();setBusy(true);
  loadArts(tag.name,page,{signal:controller.signal}).then(list=>{if(controller.signal.aborted)return;setPosts(old=>{const seen=new Set(old.map(p=>p.id));return [...old,...list.filter(p=>!seen.has(p.id))];});if(list.length<30)setDone(true);})
   .catch(()=>{if(!controller.signal.aborted)setError('Не удалось загрузить арты.');})
   .finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  return()=>controller.abort();
 },[tag?.name,page]);
 useEffect(()=>{const node=sentinel.current;if(!node||done||!tag)return;const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!busy)setPage(n=>n+1);},{rootMargin:'900px'});observer.observe(node);return()=>observer.disconnect();},[busy,done,tag?.name]);
 const current=open==null?null:posts[open];
 return <section className="art-wall" aria-labelledby="art-wall-title">
  <header className="art-wall-head">
   <div><h2 id="art-wall-title">Арты</h2><p>Рисунки фанатов по персонажу или тайтлу. Только изображения без откровенного содержания.</p></div>
   <form className="art-wall-search" role="search" onSubmit={event=>{event.preventDefault();resolve(query);}}>
    <Search size={18} aria-hidden="true"/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Например, Eren Yeager" aria-label="Персонаж или тайтл" enterKeyHint="search"/>
    {busy&&<LoaderCircle className="art-wall-spin" size={17} aria-label="Загружаем"/>}
   </form>
  </header>
  {tags.length>1&&<div className="art-wall-tags" role="group" aria-label="Что показать">{tags.map(value=><button key={value.name} type="button" aria-pressed={tag?.name===value.name} onClick={()=>pick(value)}>{value.label}<small>{value.kind==='character'?'персонаж':'тайтл'} · {value.count.toLocaleString('ru-RU')}</small></button>)}</div>}
  {error&&<p className="art-wall-note" role="status">{error}</p>}
  {!tag&&!error&&!busy&&<div className="art-wall-empty"><ImageIcon size={30} aria-hidden="true"/><p>Открой персонажа на странице тайтла и нажми «Посмотреть арты» — или найди его здесь.</p></div>}
  <div className="art-wall-board">{posts.map((post,i)=><motion.button key={post.id} type="button" className="art-pin" style={{aspectRatio:post.width+'/'+post.height}} aria-label={'Открыть арт '+(i+1)} onClick={()=>setOpen(i)}
   initial={reduce?false:{opacity:0,y:14}} animate={{opacity:1,y:0}} transition={{duration:.45,ease:[.22,1,.36,1],delay:reduce?0:Math.min(8,i%30)*.03}}>
   <img src={post.preview} alt="" loading="lazy" decoding="async" referrerPolicy="origin"/>
  </motion.button>)}</div>
  {tag&&!done&&<div ref={sentinel} className="art-wall-more" aria-hidden="true"/>}
  {tag&&done&&posts.length>0&&<p className="art-wall-note">Это все арты по запросу «{tag.label}».</p>}
  <Dialog.Root open={!!current} onOpenChange={value=>{if(!value)setOpen(null);}}>
   <AnimatePresence>{current&&<Dialog.Portal forceMount>
    <Dialog.Overlay forceMount asChild><motion.div className="dialog-overlay art-lightbox-backdrop" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}/></Dialog.Overlay>
    <Dialog.Content forceMount asChild onKeyDown={event=>{if(event.key==='ArrowRight')setOpen(n=>Math.min(posts.length-1,n+1));if(event.key==='ArrowLeft')setOpen(n=>Math.max(0,n-1));}}>
     <motion.div className="art-lightbox" initial={reduce?false:{opacity:0,scale:.96}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.98}} transition={{type:'spring',stiffness:380,damping:34}}>
      <Dialog.Title className="sr-only">Арт {open+1} из {posts.length}</Dialog.Title><Dialog.Description className="sr-only">{tag?.label}</Dialog.Description>
      <img src={current.large} alt="" referrerPolicy="origin"/>
      <div className="art-lightbox-bar">{current.artist&&<span>Автор: {current.artist}</span>}<a href={current.page} target="_blank" rel="noopener noreferrer">Источник<ExternalLink size={13}/></a><Dialog.Close className="circle-button" aria-label="Закрыть арт"><X size={18}/></Dialog.Close></div>
     </motion.div>
    </Dialog.Content>
   </Dialog.Portal>}</AnimatePresence>
  </Dialog.Root>
 </section>;
}
