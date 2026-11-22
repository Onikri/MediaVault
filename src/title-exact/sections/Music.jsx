import {useEffect, useRef, useState, useSyncExternalStore} from 'react';
import {Check, Disc3, ExternalLink, MoreHorizontal, Play, Plus} from 'lucide-react';
import {musicSnapshot, playMusic, subscribeMusic} from '../../music-player.js';
import {spotifySearch, toggleTrack, tracks, youtubeSearch} from '../../music-library.js';
import {PlaylistExport, SongDetails, songKind, useAnimeSoundtrack} from '../../Soundtrack.jsx';
import {EpisodeOst} from './EpisodeOst.jsx';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, glass, useEntered} from './ui.jsx';

/* Музыка: one row of square cards: the cover, OP/ED and where it plays, the
   song and its artists, «Слушать» into the navbar island and «В любимые». */
function More({t, onExport, isNoir}) {
  const [open, setOpen] = useState(false), [about, setAbout] = useState(false), box = useRef(null);
  useEffect(() => {
    if (!open) return;
    const away = e => { if (!box.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);
  const item = 'w-full flex items-center justify-between gap-3 px-3 py-2 rounded-xl text-left text-[12px] text-zinc-200 hover:bg-white/[0.06] hover:text-white';
  return <div ref={box} className="relative">
    <button type="button" aria-label={'Ещё действия: ' + t.title} aria-expanded={open} onClick={() => setOpen(v => !v)} className="w-8 h-8 grid place-items-center rounded-full bg-white/[0.04] border border-white/[0.08] text-zinc-400 hover:text-white"><MoreHorizontal size={14}/></button>
    {open && <div className={`absolute right-0 top-[calc(100%+8px)] z-30 w-60 p-1.5 rounded-2xl border backdrop-blur-2xl shadow-[0_24px_60px_-20px_rgba(0,0,0,0.9)] ${isNoir ? 'bg-black/90 border-white/20' : 'bg-[#12080d]/90 border-white/[0.1]'}`}>
      <a className={item} href={youtubeSearch(t)} target="_blank" rel="noopener noreferrer">Найти в YouTube Music<ExternalLink size={12}/></a>
      <a className={item} href={spotifySearch(t)} target="_blank" rel="noopener noreferrer">Найти в Spotify<ExternalLink size={12}/></a>
      <button type="button" className={item} onClick={() => { setOpen(false); onExport(t); }}>Добавить в плейлист платформы</button>
      <button type="button" className={item} aria-expanded={about} onClick={() => setAbout(v => !v)}>О песне</button>
      {about && <div className="px-3 pb-2 text-[12px] text-zinc-300 [&_a]:text-zinc-400 [&_a:hover]:text-white"><SongDetails track={t}/></div>}
    </div>}
  </div>;
}

export function MusicSection({k, isNoir, identity, animeTitle, cover, userId, renderArtwork}) {
  const {data, error, retry} = useAnimeSoundtrack(identity, animeTitle);
  const current = useSyncExternalStore(subscribeMusic, musicSnapshot);
  const [saved, setSaved] = useState(() => tracks(userId)), [exporting, setExporting] = useState(null), [ref, entered] = useEntered();
  useEffect(() => { const update = () => setSaved(tracks(userId)); update(); addEventListener('mediavault-music', update); return () => removeEventListener('mediavault-music', update); }, [userId]);
  const all = (data?.tracks || []).map(t => ({...t, animeCover: cover}));
  const values = all.filter(t => t.artists?.length || !all.some(x => x !== t && x.type === t.type && x.title.toLowerCase() === t.title.toLowerCase() && x.artists?.length));
  const queue = values.map(v => ({...v, cover: v.cover || v.animeCover}));
  return <section id="titleMusic" ref={ref}>
    <SectionFrame>
      {!values.length ? <p className="text-[13px] text-zinc-400" role="status">{error || (!data ? 'Ищем названия песен…' : 'Каталог пока не предоставил музыкальные темы.')}{error && <button type="button" className="ml-2 underline underline-offset-4" onClick={retry}>Повторить</button>}</p>
        : <div translate="no" className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {values.map((t, idx) => {
            const art = t.cover || t.animeCover, active = current?.track?.id === t.id, isSaved = saved.some(v => v.id === t.id);
            const play = () => playMusic({...t, cover: art}, queue);
            return <KineticItem key={t.id} weight={0.8 + (idx % 3) * 0.12} drift={(idx % 3) - 1} {...k}>
              <article className={`group relative flex items-center gap-3.5 p-2.5 pr-3 rounded-[20px] border transition-all duration-500 ${active ? (isNoir ? 'bg-white/[0.08] border-white/40' : 'bg-rose-950/30 border-rose-400/35 shadow-[0_18px_40px_-22px_rgba(225,29,72,0.7)]') : `${glass(isNoir)} hover:border-white/20`} ${entered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'}`}
                style={{transitionDelay: entered ? `${Math.min(idx, 9) * 50}ms` : '0ms'}}>
                <button type="button" onClick={play} aria-label={(active ? 'Играет: ' : 'Включить ') + t.title} className="relative w-16 h-16 shrink-0 rounded-2xl overflow-hidden bg-white/[0.04]">
                  {art ? <span className={`absolute inset-0 kt-cover transition-transform duration-700 ${active ? 'scale-110' : 'group-hover:scale-110'} ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(art)}</span>
                    : <span className="absolute inset-0 grid place-items-center text-zinc-600"><Disc3 size={24}/></span>}
                  <span className={`absolute inset-0 grid place-items-center transition-all duration-300 ${active ? 'bg-black/45 opacity-100' : 'bg-black/40 opacity-0 group-hover:opacity-100'}`}>
                    {active ? <span className="flex items-end gap-[2px] h-4" aria-hidden="true">{[0, 1, 2, 3].map(b => <span key={b} className="w-[3px] h-full rounded-full bg-white" style={{animation: `mvEq .8s ${b * .12}s ease-in-out infinite alternate`}}/>)}</span>
                      : <span className={`grid place-items-center w-9 h-9 rounded-full ${isNoir ? 'bg-white text-black' : 'bg-rose-600 text-white shadow-[0_0_18px_rgba(225,29,72,0.6)]'}`}><Play size={14} fill="currentColor" className="ml-0.5"/></span>}
                  </span>
                </button>
                <span className="flex-1 min-w-0">
                  <span className={`flex items-center gap-1.5 text-[9px] uppercase tracking-[0.16em] ${isNoir ? 'text-zinc-300' : 'text-rose-300/90'}`}>{t.type && <b className={`font-mono font-bold px-1.5 rounded ${isNoir ? 'bg-white text-black' : 'bg-rose-500/20 text-rose-200'}`}>{t.type}{t.sequence || ''}</b>}<span className="truncate">{songKind(t)}</span></span>
                  <span className="block mt-1 text-[14px] font-black tracking-tight text-white truncate" title={t.title}>{t.title}</span>
                  <span className="block text-[11px] text-zinc-400 truncate" title={t.artists?.join(', ')}>{t.artists?.join(', ') || 'Исполнитель не указан'}</span>
                </span>
                <span className="flex items-center gap-1 shrink-0">
                  <button type="button" aria-pressed={isSaved} aria-label={(isSaved ? 'Убрать ' : 'Сохранить ') + t.title} title={isSaved ? 'В любимых' : 'В любимые'} onClick={() => setSaved(toggleTrack(userId, {...t, cover: art}))}
                    className={`grid place-items-center w-8 h-8 rounded-full border transition-colors ${isSaved ? (isNoir ? 'bg-white/15 border-white/40 text-white' : 'bg-rose-500/15 border-rose-400/40 text-rose-200') : 'bg-white/[0.04] border-white/[0.08] text-zinc-400 hover:text-white'}`}>{isSaved ? <Check size={13}/> : <Plus size={13}/>}</button>
                  <More t={t} isNoir={isNoir} onExport={setExporting}/>
                </span>
              </article>
            </KineticItem>;
          })}
        </div>}
      <p className="text-[11px] text-zinc-500">Источник: {data?.source || 'AnimeThemes и MyAnimeList'}{data?.stale ? ', сохранённые титры' : ''}. Сохраняется только название песни, аудио не скачивается.</p>
      <EpisodeOst identity={identity} isNoir={isNoir}/>
    </SectionFrame>
    <PlaylistExport track={exporting} onClose={() => setExporting(null)}/>
  </section>;
}
