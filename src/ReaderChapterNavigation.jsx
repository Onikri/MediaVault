import {BookOpen} from 'lucide-react';
import UiSelect from './UiSelect.jsx';
import './chapter-scrub.css';
const volume=chapter=>Number(chapter.season)||1;
const label=chapter=>chapter.episodeTitle||'Глава '+(chapter.episode??'?');
export function ReaderChapterMenu({chapters,item,onChoose}){
 const current=volume(item),volumes=[...new Set(chapters.map(volume))];
 return <div className="reader-chapter-menu">
 {volumes.length>1&&<UiSelect aria-label="Перейти к тому" value={current} onChange={e=>onChoose(chapters.find(c=>volume(c)===Number(e.target.value)))}>{volumes.map(v=><option key={v} value={v}>Том {v}</option>)}</UiSelect>}
 <UiSelect aria-label="Перейти к главе" value={item.id} onChange={e=>onChoose(chapters.find(c=>c.id===e.target.value))}>{chapters.filter(c=>volume(c)===current).map(c=><option key={c.id} value={c.id}>{label(c)}</option>)}</UiSelect>
 </div>;
}
export function ReaderChapterShelf({chapters,item,onChoose}){
 return <nav className="reader-chapter-shelf" aria-label="Главы произведения">{chapters.length?chapters.map(c=><button type="button" className="reader-chapter-mini" key={c.id} aria-current={c.id===item.id} onClick={()=>onChoose(c)}><span>{c.preview?<img src={c.preview} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<BookOpen size={28}/>}<b>{c.episode??'—'}</b></span><strong>{label(c)}</strong><small>Том {volume(c)}</small></button>):<p className="reader-empty">Открыта отдельная глава.</p>}</nav>;
}
