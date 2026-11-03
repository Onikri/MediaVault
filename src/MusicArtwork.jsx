import {useState} from 'react';
import {Music2} from 'lucide-react';
import {musicArtworkCrop} from './music-artwork.js';

// Cropping, rotation and the parent cover's spring scale have separate layers.
// Keep the rotation animation mounted while paused so its angle is retained.
export default function MusicArtwork({src,playing,onError}){
 const [size,setSize]=useState(null);
 const crop=musicArtworkCrop(src,size?.src===src?size.width:0,size?.src===src?size.height:0);
 return <span className="music-artwork" aria-hidden="true"><span className={'music-artwork-vinyl'+(src&&playing?' is-spinning':'')}>
  {src?<img src={src} alt="" draggable={false} referrerPolicy="no-referrer" style={{transform:`scale(${crop})`}}
   onLoad={event=>{const image=event.currentTarget;setSize({src,width:image.naturalWidth,height:image.naturalHeight});}}
   onError={onError}/>:<Music2 size={18}/>}
 </span></span>;
}
