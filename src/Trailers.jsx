import {useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {Play,X,Film} from 'lucide-react';
import YouTubeEmbed from './YouTubeEmbed.jsx';
export default function Trailers({profile,renderArtwork,onPlaybackChange}){
 const[selected,setSelected]=useState(null);
 if(!profile.trailers?.length)return null;
 return <section className="title-trailers"><div className="section-heading"><h2><Film size={17}/>Трейлеры и проморолики</h2><span className="fine">YouTube</span></div><div className="trailer-grid">{profile.trailers.map((v,i)=><button key={v.id} onClick={()=>setSelected(v)}><span className="trailer-cover">{renderArtwork(v)}<span className="trailer-play"><Play size={23} fill="currentColor"/></span><small>{String(i+1).padStart(2,'0')}</small></span><strong>{v.title}</strong></button>)}</div>
 <Dialog.Root open={!!selected} onOpenChange={open=>{if(!open){setSelected(null);onPlaybackChange?.(false);}}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="trailer-dialog"><div className="trailer-dialog-heading"><div><Dialog.Title>{selected?.title}</Dialog.Title><Dialog.Description>{profile.title} · YouTube</Dialog.Description></div><Dialog.Close className="icon-button" aria-label="Закрыть трейлер"><X size={19}/></Dialog.Close></div>{selected&&<YouTubeEmbed videoId={selected.id} title={selected.title} autoplay onState={s=>onPlaybackChange?.(s===1)}/>}</Dialog.Content></Dialog.Portal></Dialog.Root></section>;
}
