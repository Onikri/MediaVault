import {useState} from 'react';
import {ExternalLink,Play} from 'lucide-react';
import YouTubeEmbed from './YouTubeEmbed.jsx';
import './watch-page.css';

export default function OfficialSeriesPlayer({title,source}){
 const [episode,setEpisode]=useState(0);
 const [part,setPart]=useState(0);
 const [started,setStarted]=useState(false);
 const current=source.episodes[episode];
 const videoId=current.parts[part];
 const label=title+' · Серия '+current.number+' · Часть '+(part+1);

 return <section className="official-series" aria-label={'Источник '+source.publisher}>
  <div className="official-series-heading">
   <div><a href={current.url} target="_blank" rel="noopener noreferrer">{source.publisher} <ExternalLink size={12}/></a><small>{source.audio} · {source.subtitles}</small></div>
   <label>Серия <select aria-label="Серия GMMTV" value={episode} onChange={event=>{setEpisode(Number(event.target.value));setPart(0);}}>
    {source.episodes.map((row,index)=><option key={row.number} value={index}>{row.number}</option>)}
   </select></label>
  </div>
  <div className="official-series-parts" aria-label={'Части серии '+current.number} role="group">
   {current.parts.map((_,index)=><button key={index} type="button" className="btn btn-secondary btn-small"
    aria-pressed={part===index} onClick={()=>setPart(index)}>Часть {index+1}</button>)}
  </div>
  {started
   ?<YouTubeEmbed key={videoId} videoId={videoId} title={label} captionLanguage="en" autoplay
    onState={state=>{if(state===0&&part+1<current.parts.length)setPart(part+1);}}/>
   :<button type="button" className="btn btn-primary btn-small" onClick={()=>setStarted(true)}><Play size={16}/> Смотреть часть {part+1}</button>}
 </section>;
}
