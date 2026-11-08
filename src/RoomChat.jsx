import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Send,Smile,Reply,Trash2,SmilePlus,X,ArrowDown,Search} from 'lucide-react';
import {EMOJI_GROUPS,QUICK_REACTIONS,recentEmoji,rememberEmoji,jumboEmoji} from './emoji-data.js';
import './room-chat.css';
import {uiLocale} from './i18n/index.js';

// Room chat in the spirit of Discord/Telegram: grouped messages, replies,
// reactions, typing hints, emoji and GIFs. Server keeps a short history so
// late joiners see the conversation.
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))%360;return h;}
const time=at=>new Date(at*1000).toLocaleTimeString(uiLocale(),{hour:'2-digit',minute:'2-digit'});
function Linkified({text}){
 return text.split(/(https?:\/\/[^\s<>"]+)/g).map((part,i)=>i%2?<a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow">{part}</a>:part);
}
function typingLine(typing){
 const names=Object.values(typing).map(v=>v.name).filter(Boolean);
 if(!names.length)return '';
 if(names.length===1)return names[0]+' печатает';
 if(names.length===2)return names[0]+' и '+names[1]+' печатают';
 return 'Несколько человек печатают';
}

function EmojiPicker({onPick,onClose}){
 const [group,setGroup]=useState(()=>recentEmoji().length?'recent':'faces'),recent=useMemo(recentEmoji,[]);
 const groups=[...(recent.length?[{id:'recent',label:'Недавние',items:recent}]:[]),...EMOJI_GROUPS],current=groups.find(g=>g.id===group)||groups[0];
 useEffect(()=>{const key=e=>{if(e.key==='Escape')onClose();};addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[]);
 return <motion.div className="rcx-pop rcx-emoji" role="dialog" aria-label="Эмодзи" initial={{opacity:0,y:8,scale:.97}} animate={{opacity:1,y:0,scale:1}} exit={{opacity:0,y:8,scale:.97}} transition={{duration:.16}}>
  <div className="rcx-emoji-tabs" role="tablist">{groups.map(g=><button key={g.id} type="button" role="tab" aria-selected={g.id===current.id} title={g.label} onClick={()=>setGroup(g.id)}>{g.items[0]}</button>)}</div>
  <p className="rcx-pop-title">{current.label}</p>
  <div className="rcx-emoji-grid">{current.items.map(e=><button key={e} type="button" aria-label={e} onClick={()=>{rememberEmoji(e);onPick(e);}}>{e}</button>)}</div>
 </motion.div>;
}

function GifPicker({search,onPick,onClose}){
 const [query,setQuery]=useState(''),[results,setResults]=useState([]),[state,setState]=useState('loading'),[error,setError]=useState('');
 useEffect(()=>{const key=e=>{if(e.key==='Escape')onClose();};addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[]);
 useEffect(()=>{const abort=new AbortController();setState('loading');const timer=setTimeout(()=>search(query.trim(),0,abort.signal).then(v=>{setResults(v);setState(v.length?'ready':'empty');}).catch(e=>{if(e.name==='AbortError')return;setError(e.message);setState('error');}),query?350:0);return()=>{clearTimeout(timer);abort.abort();};},[query]);
 return <motion.div className="rcx-pop rcx-gifs" role="dialog" aria-label="GIF" initial={{opacity:0,y:8,scale:.97}} animate={{opacity:1,y:0,scale:1}} exit={{opacity:0,y:8,scale:.97}} transition={{duration:.16}}>
  <label className="rcx-gif-search"><Search size={15}/><input autoFocus value={query} onChange={e=>setQuery(e.target.value)} placeholder="Найти GIF" aria-label="Найти GIF" maxLength={60}/></label>
  {state==='error'?<p className="rcx-pop-note">{error}</p>:state==='empty'?<p className="rcx-pop-note">Ничего не нашлось. Попробуй другое слово.</p>:
   <div className={'rcx-gif-grid'+(state==='loading'?' is-loading':'')}>{results.map(g=><button key={g.id||g.url} type="button" onClick={()=>onPick(g)} aria-label={g.title||'GIF'} style={{aspectRatio:g.width+'/'+g.height}}><img src={g.preview} alt="" loading="lazy"/></button>)}</div>}
  <p className="rcx-pop-credit">Работает на GIPHY</p>
 </motion.div>;
}

function Message({m,grouped,me,canDelete,mention,conversation,onReply,onReact,onJump,live,open,onToggle}){
 const reduce=useReducedMotion(),reactions=Object.entries(m.reactions||{}),avatar=conversation.resolve(m.avatar);
 const jumbo=!m.gif&&jumboEmoji(m.text);
 return <motion.li data-id={m.id} className={'rcx-msg'+(grouped?' is-grouped':'')+(avatar?'':' no-avatar')+(m.from===me?' is-mine':'')+(mention?' is-mention':'')+(open?' is-open':'')} onClick={e=>{if(!e.target.closest('button,a'))onToggle(m.id);}} initial={live&&!reduce?{opacity:0,y:10}:false} animate={{opacity:1,y:0}} exit={reduce?undefined:{opacity:0,height:0,marginTop:0}} transition={{duration:.2,ease:[.16,1,.3,1]}} layout={reduce?false:'position'}>
  <div className="rcx-gutter">{!grouped&&avatar?<img className="rcx-avatar" src={avatar} alt=""/>:grouped?<time className="rcx-side-time" dateTime={new Date(m.at*1000).toISOString()}>{time(m.at)}</time>:null}</div>
  <div className="rcx-body" translate="no">
   {!grouped&&<p className="rcx-meta"><strong style={{'--author-hue':hue(m.from)}}>{m.name}</strong><time dateTime={new Date(m.at*1000).toISOString()}>{time(m.at)}</time></p>}
   {m.reply&&<button type="button" className="rcx-quote" onClick={()=>onJump(m.reply.id)}><strong>{m.reply.name}</strong><span>{m.reply.text}</span></button>}
   {m.text&&<p className={'rcx-text'+(jumbo?' is-jumbo':'')}><Linkified text={m.text}/></p>}
   {m.gif&&<img className="rcx-gif" src={m.gif.url} width={m.gif.width} height={m.gif.height} alt={m.gif.title||'GIF'} loading="lazy" style={{aspectRatio:m.gif.width+'/'+m.gif.height}}/>}
   {reactions.length>0&&<div className="rcx-reactions">{reactions.map(([emoji,people])=>{const mine=people.includes(me),names=people.map(id=>conversation.members.find(x=>x.id===id)?.name).filter(Boolean).join(', ');return <motion.button key={emoji} type="button" aria-pressed={mine} title={names} onClick={()=>conversation.react(m.id,emoji)} initial={reduce?false:{scale:.6}} animate={{scale:1}} transition={{type:'spring',stiffness:600,damping:22}}>{emoji}<AnimatePresence mode="popLayout" initial={false}><motion.span key={people.length} initial={reduce?false:{y:-8,opacity:0}} animate={{y:0,opacity:1}} exit={reduce?undefined:{y:8,opacity:0}} transition={{duration:.15}}>{people.length}</motion.span></AnimatePresence></motion.button>;})}</div>}
  </div>
  <div className="rcx-actions" role="toolbar" aria-label="Действия с сообщением" onClick={()=>open&&onToggle(m.id)}>
   {QUICK_REACTIONS.slice(0,4).map(e=><button key={e} type="button" aria-label={'Реакция '+e} onClick={()=>conversation.react(m.id,e)}>{e}</button>)}
   <button type="button" aria-label="Другая реакция" title="Другая реакция" onClick={()=>onReact(m.id)}><SmilePlus size={16}/></button>
   <button type="button" aria-label="Ответить" title="Ответить" onClick={()=>onReply(m)}><Reply size={16}/></button>
   {canDelete&&<button type="button" className="is-danger" aria-label="Удалить сообщение" title="Удалить" onClick={()=>conversation.remove(m.id)}><Trash2 size={15}/></button>}
  </div>
 </motion.li>;
}

export default function RoomChat({conversation}){
 const [text,setText]=useState(''),[open,setOpen]=useState(null),[reply,setReply]=useState(null),[panel,setPanel]=useState(null),[unread,setUnread]=useState(0);
 const scroller=useRef(null),field=useRef(null),pinned=useRef(true),count=useRef(0),mountedAt=useRef(Date.now()/1000),reduce=useReducedMotion();
 const me=conversation.memberId,self=conversation.members.find(m=>m.id===me),host=!!self?.host;
 const messages=conversation.messages;
 const mentionPattern=useMemo(()=>self?.name&&self.name.length>1?new RegExp('(^|[^\\p{L}])@?'+self.name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?![\\p{L}])','iu'):null,[self?.name]);
 // Stick to the newest message unless the reader scrolled up; then count.
 useLayoutEffect(()=>{
  const box=scroller.current;if(!box)return;const added=messages.length-count.current;count.current=messages.length;
  if(pinned.current||added<0||messages[messages.length-1]?.from===me){box.scrollTop=box.scrollHeight;setUnread(0);}else if(added>0)setUnread(n=>n+added);
 },[messages]);
 // A card or sheet opening above the chat shrinks it; keep the newest message in view.
 useEffect(()=>{const box=scroller.current;if(!box||typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(()=>{if(pinned.current)box.scrollTop=box.scrollHeight;});observer.observe(box);return()=>observer.disconnect();},[]);
 const onScroll=()=>{const box=scroller.current;pinned.current=box.scrollHeight-box.scrollTop-box.clientHeight<60;if(pinned.current)setUnread(0);};
 const toBottom=()=>{const box=scroller.current;box.scrollTo({top:box.scrollHeight,behavior:reduce?'auto':'smooth'});setUnread(0);};
 const jump=id=>{const node=scroller.current?.querySelector(`[data-id="${CSS.escape(id)}"]`);if(!node)return;node.scrollIntoView({block:'center',behavior:reduce?'auto':'smooth'});node.classList.remove('is-flash');void node.offsetWidth;node.classList.add('is-flash');};
 // Grow the composer with its text, up to five lines.
 useLayoutEffect(()=>{const el=field.current;if(!el)return;el.style.height='auto';el.style.height=Math.min(el.scrollHeight,120)+'px';},[text]);
 function send(event){event?.preventDefault();if(!conversation.connected||!text.trim())return;conversation.post(text,{reply:reply?.id});setText('');setReply(null);pinned.current=true;}
 function insert(emoji){const el=field.current,start=el?.selectionStart??text.length,end=el?.selectionEnd??text.length;const next=text.slice(0,start)+emoji+text.slice(end);setText(next);requestAnimationFrame(()=>{el?.focus();el?.setSelectionRange(start+emoji.length,start+emoji.length);});}
 const line=typingLine(conversation.typing||{});
 return <div className="rcx">
  <div className="rcx-head"><span>Чат</span></div>
  <div ref={scroller} className="rcx-scroll" onScroll={onScroll}>
   {!messages.length?<p className="rcx-empty">Здесь пока тихо. Напиши первым, когда начнётся серия.</p>:
   <ol className="rcx-list" aria-live="polite" aria-relevant="additions"><AnimatePresence initial={false}>{messages.map((m,i)=>{const prev=messages[i-1],grouped=!!prev&&prev.from===m.from&&m.at-prev.at<300&&!m.reply;return <Message key={m.id} m={m} grouped={grouped} me={me} canDelete={m.from===me||host} mention={m.from!==me&&!!mentionPattern?.test(m.text)} conversation={conversation} live={m.at>mountedAt.current} open={open===m.id} onToggle={v=>setOpen(o=>o===v?null:v)} onReply={v=>{setReply({id:v.id,name:v.name,text:v.text||'GIF'});field.current?.focus();}} onReact={id=>setPanel({react:id})} onJump={jump}/>;})}</AnimatePresence></ol>}
  </div>
  <AnimatePresence>{unread>0&&<motion.button type="button" className="rcx-unread" onClick={toBottom} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:8}}><ArrowDown size={14}/>{unread===1?'Новое сообщение':unread+' новых'}</motion.button>}</AnimatePresence>
  <p className="rcx-typing" aria-live="polite">{line&&<>{line}<span className="rcx-ellipsis" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span></>}</p>
  <AnimatePresence>{reply&&<motion.div className="rcx-replying" initial={{opacity:0,height:0}} animate={{opacity:1,height:'auto'}} exit={{opacity:0,height:0}}><Reply size={14}/><span>Ответ <strong>{reply.name}</strong>: {reply.text}</span><button type="button" aria-label="Отменить ответ" onClick={()=>setReply(null)}><X size={14}/></button></motion.div>}</AnimatePresence>
  <form className="rcx-compose" onSubmit={send}>
   <textarea ref={field} rows={1} aria-label="Сообщение в комнате" value={text} maxLength={2000} placeholder={conversation.connected?'Написать в чат':'Нет соединения'} disabled={!conversation.connected}
    onChange={e=>{setText(e.target.value);if(e.target.value)conversation.notifyTyping();}}
    onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send();}else if(e.key==='Escape'&&reply)setReply(null);}}/>
   <button type="button" className="rcx-tool" aria-label="Эмодзи" aria-expanded={panel==='emoji'} onClick={()=>setPanel(p=>p==='emoji'?null:'emoji')}><Smile size={18}/></button>
   <button type="button" className="rcx-tool rcx-gif-button" aria-label="GIF" aria-expanded={panel==='gif'} disabled={!conversation.connected} onClick={()=>setPanel(p=>p==='gif'?null:'gif')}>GIF</button>
   <motion.button whileTap={reduce?undefined:{scale:.88}} className="rcx-send" aria-label="Отправить сообщение" disabled={!conversation.connected||!text.trim()}><Send size={16}/></motion.button>
  </form>
  <AnimatePresence>
   {(panel==='emoji'||panel?.react)&&<EmojiPicker key="emoji" onClose={()=>setPanel(null)} onPick={e=>{if(panel?.react)conversation.react(panel.react,e);else insert(e);setPanel(null);}}/>}
   {panel==='gif'&&<GifPicker key="gif" search={conversation.searchGifs} onClose={()=>setPanel(null)} onPick={g=>{conversation.post('',{gif:g,reply:reply?.id});setReply(null);setPanel(null);pinned.current=true;}}/>}
  </AnimatePresence>
 </div>;
}
