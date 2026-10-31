import { createPortal } from 'react-dom';
import { Captions, Star, Tv } from 'lucide-react';
import type { Anime } from '../types/anime';
import { safeSynopsis, scoreLabel } from '../utils/display';

export interface AnimeHoverPreviewProps { anime:Anime; anchor:DOMRect | null; open:boolean }
/**
 * Portaled to document.body so horizontally scrollable carousel rails do not
 * clip the preview, approximating the Radix HoverCard portal in the Vite chunk.
 */
export function AnimeHoverPreview({anime,anchor,open}:AnimeHoverPreviewProps) {
  if(!anchor || !open) return null;
  const width=Math.min(325,window.innerWidth-24);
  const chooseLeft=window.innerWidth-anchor.right < width+18;
  const rawLeft=chooseLeft?anchor.left-width-13:anchor.right+13;
  const left=Math.min(Math.max(12,rawLeft),window.innerWidth-width-12);
  const top=Math.min(Math.max(220,anchor.top+anchor.height/2),window.innerHeight-230);
  return createPortal(<aside className="anime-preview is-portal is-open" style={{left,top,width}} role="tooltip">
    <div className="preview-head"><h3>{anime.title}</h3><span className="score-pill"><Star size={14} fill="currentColor"/> {scoreLabel(anime.score)}</span></div>
    <p className="preview-synopsis">{safeSynopsis(anime)}</p>
    <div className="preview-chips">{anime.type&&<span><Tv size={14}/>{anime.type}</span>}{anime.episodes&&<span><Captions size={14}/> {anime.episodes} сер.</span>}</div>
    <dl className="preview-specs"><dt>ОРИГИНАЛ</dt><dd>{anime.title_japanese || '—'}</dd><dt>ВЫПУСК</dt><dd>{anime.aired?.string || anime.year || '—'}</dd><dt>СТАТУС</dt><dd>{anime.status || '—'}</dd><dt>ЖАНРЫ</dt><dd>{anime.genres?.map(genre=>genre.name).join(', ')||'—'}</dd></dl>
  </aside>,document.body);
}
