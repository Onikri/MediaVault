import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Music2,Play,X} from 'lucide-react';
import './player-song-cue.css';

// Shares the pause-title position; never floats over the episode selectors.
export default function PlayerSongCue({track,theme,visible,onDismiss,onPlay}){
 const reduce=useReducedMotion();
 return <AnimatePresence initial={false}>{track&&visible&&<motion.div key={track.id} className="player-song-cue" role="status" initial={reduce?false:{opacity:0,y:5}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-3}} transition={{duration:reduce?0:.2}}>
  <small><Music2 size={12}/>{theme==='OP'?'Опенинг':'Эндинг'} · сейчас звучит</small>
  <div><span><strong title={track.title}>{track.title}</strong><span>{track.artists?.join(', ')}</span></span><button aria-label={'Слушать отдельно '+track.title} onClick={onPlay}><Play size={15}/></button><button aria-label="Скрыть песню" onClick={onDismiss}><X size={13}/></button></div>
 </motion.div>}</AnimatePresence>;
}
