import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ExternalLink,Music2,Play,X} from 'lucide-react';
import {spotifyTrackUrl} from './use-episode-ost.js';
import './player-song-cue.css';

// A low "record" card while an opening or ending plays: play sits on the cover.
export default function PlayerSongCue({track,theme,visible,onDismiss,onPlay}){
 const reduce=useReducedMotion();
 return <AnimatePresence initial={false}>{track&&visible&&<motion.aside key={track.id} className="mvx-song" role="status" initial={reduce?false:{opacity:0,y:-8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-4}} transition={{duration:reduce?0:.2}}>
  <button type="button" className="mvx-song-cover" aria-label={'Слушать отдельно '+track.title} onClick={onPlay}>{track.cover?<img src={track.cover} alt="" referrerPolicy="no-referrer"/>:<Music2 size={18} style={{position:'absolute',opacity:.4}}/>}<span><Play size={13} fill="currentColor" strokeWidth={0}/></span></button>
  <div className="mvx-song-body">
   <strong title={track.title}>{track.title}</strong>
   <span>{[theme==='OP'?'Опенинг':theme==='ED'?'Эндинг':'Сейчас звучит',track.artists?.join(', ')].filter(Boolean).join(' · ')}</span>
  </div>
  {spotifyTrackUrl(track.spotify)&&<a className="mvx-song-close" href={spotifyTrackUrl(track.spotify)} target="_blank" rel="noopener noreferrer" aria-label="Открыть официальный трек в Spotify" title="Официальный трек в Spotify"><ExternalLink size={14}/></a>}
  <button type="button" className="mvx-song-close" aria-label="Скрыть песню" onClick={onDismiss}><X size={14}/></button>
 </motion.aside>}</AnimatePresence>;
}
