import {BookOpen,Play} from 'lucide-react';

export default function TitleEpisodeCard({number,title,detail,artwork,manga=false,onClick,selected,...interaction}){
 return <button type="button" className="title-episode-card" aria-pressed={selected} onClick={onClick} {...interaction}>
  <span className="title-episode-art">{artwork}<span>{manga?<BookOpen size={20}/>:<Play size={20} fill="currentColor"/>}</span><b>{String(number).padStart(2,'0')}</b></span>
  <strong>{title}</strong>{detail&&<small>{detail}</small>}
 </button>;
}
