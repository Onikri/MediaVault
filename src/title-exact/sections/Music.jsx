import {useEffect, useRef, useState, useSyncExternalStore} from 'react';
import {Check, Disc3, ExternalLink, MoreHorizontal, Play, Plus} from 'lucide-react';
import {musicSnapshot, playMusic, subscribeMusic} from '../../music-player.js';
import {spotifySearch, toggleTrack, tracks, youtubeSearch} from '../../music-library.js';
import {PlaylistExport, SongDetails, songKind, useAnimeSoundtrack} from '../../Soundtrack.jsx';
import EpisodeSoundtrack from '../../EpisodeSoundtrack.jsx';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, rowScroll, useEntered} from './ui.jsx';

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
    <button type="button" aria-label={'Ещё действия: ' + t.title} aria-expanded={open} onClick={() => setOpen(v => !v)} className="w-9 h-9 grid place-items-center rounded-full bg-white/[0.05] border border-white/[0.1] text-zinc-300 hover:text-white"><MoreHorizontal size={15}/></button>
    {open && <div className={`absolute right-0 bottom-[calc(100%+8px)] z-20 w-60 p-1.5 rounded-2xl border backdrop-blur-2xl shadow-[0_24px_60px_-20px_rgba(0,0,0,0.9)] ${isNoir ? 'bg-black/90 border-white/20' : 'bg-[#12080d]/90 border-white/[0.1]'}`}>
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
        : <div translate="no" className={`grid grid-flow-col auto-cols-[82%] sm:auto-cols-[calc((100%-20px)/2)] lg:auto-cols-[calc((100%-40px)/3.25)] gap-5 ${rowScroll}`}>
          {values.map((t, idx) => {
            const art = t.cover || t.animeCover, active = current?.track?.id === t.id, isSaved = saved.some(v => v.id === t.id);
            const play = () => playMusic({...t, cover: art}, queue);
            return <KineticItem key={t.id} weight={0.76 + (idx % 3) * 0.16} drift={(idx % 3) - 1} {...k}>
              <article className={`group relative snap-start rounded-3xl border transition-all duration-700 ${active ? (isNoir ? 'border-white/50' : 'border-rose-400/40 shadow-[0_30px_70px_-30px_rgba(225,29,72,0.7)]') : isNoir ? 'border-white/20' : 'border-white/[0.08]'} ${entered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-12'}`}
                style={{transitionDelay: entered ? `${Math.min(idx, 6) * 80}ms` : '0ms'}}>
                <div className="relative aspect-square overflow-hidden rounded-t-3xl bg-white/[0.03]">
                  {art ? <span className={`absolute inset-0 kt-cover transition-transform duration-[1.4s] ease-out ${active ? 'scale-110' : 'group-hover:scale-105'} ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(art)}</span>
                    : <span className="absolute inset-0 grid place-items-center text-zinc-600"><Disc3 size={40}/></span>}
                  <span className="absolute inset-0 bg-gradient-to-t from-[#0c070a] via-black/20 to-transparent"/>
                  {t.type && <span className={`absolute top-4 left-4 px-2.5 py-1 rounded-full text-[10px] font-mono font-bold tracking-[0.12em] backdrop-blur-md border ${isNoir ? 'bg-white text-black border-white' : 'bg-black/40 text-white border-white/20'}`}>{t.type}{t.sequence || ''}</span>}
                  <button type="button" onClick={play} aria-label={(active ? 'Играет: ' : 'Включить ') + t.title}
                    className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-full grid place-items-center transition-all duration-500 ${active ? 'scale-100 opacity-100' : 'scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:scale-100'} ${isNoir ? 'bg-white text-black' : 'bg-rose-600 text-white shadow-[0_0_40px_rgba(225,29,72,0.6)]'}`}>
                    {active ? <span className="flex items-end gap-[3px] h-5" aria-hidden="true">{[0, 1, 2, 3].map(b => <span key={b} className={`w-[3px] rounded-full ${isNoir ? 'bg-black' : 'bg-white'}`} style={{animation: `mvEq .8s ${b * .12}s ease-in-out infinite alternate`}}/>)}</span> : <Play size={22} fill="currentColor" className="ml-1"/>}
                  </button>
                </div>
                <div className={`relative p-5 rounded-b-3xl ${isNoir ? 'bg-black' : 'bg-[#0c070a]'}`}>
                  <p className={`text-[10px] uppercase tracking-[0.2em] truncate ${isNoir ? 'text-zinc-300' : 'text-rose-300/90'}`}>{songKind(t)}</p>
                  <p className="mt-1.5 text-lg font-black tracking-tight text-white truncate" title={t.title}>{t.title}</p>
                  <p className="text-[13px] text-zinc-400 truncate" title={t.artists?.join(', ')}>{t.artists?.join(', ') || 'Исполнитель не указан'}</p>
                  <div className="mt-4 flex items-center gap-2">
                    <button type="button" onClick={play} className={`h-9 px-4 rounded-full text-[12px] font-semibold flex items-center gap-2 ${isNoir ? 'bg-white text-black' : 'bg-rose-600 hover:bg-rose-500 text-white'}`}><Play size={13} fill="currentColor"/>{active ? 'Играет' : 'Слушать'}</button>
                    <button type="button" aria-pressed={isSaved} aria-label={(isSaved ? 'Убрать ' : 'Сохранить ') + t.title} onClick={() => setSaved(toggleTrack(userId, {...t, cover: art}))}
                      className={`h-9 px-4 rounded-full text-[12px] font-medium border flex items-center gap-2 transition-all ${isSaved ? (isNoir ? 'bg-white/15 border-white/40 text-white' : 'bg-rose-500/15 border-rose-400/40 text-rose-200') : 'bg-white/[0.05] border-white/[0.1] text-zinc-300 hover:text-white'}`}>{isSaved ? <Check size={13}/> : <Plus size={13}/>}{isSaved ? 'В любимых' : 'В любимые'}</button>
                    <span className="ml-auto"><More t={t} isNoir={isNoir} onExport={setExporting}/></span>
                  </div>
                </div>
              </article>
            </KineticItem>;
          })}
        </div>}
      <p className="text-[11px] text-zinc-500">Источник: {data?.source || 'AnimeThemes и MyAnimeList'}{data?.stale ? ', сохранённые титры' : ''}. Сохраняется только название песни, аудио не скачивается.</p>
      <EpisodeSoundtrack identity={identity}/>
    </SectionFrame>
    <PlaylistExport track={exporting} onClose={() => setExporting(null)}/>
  </section>;
}
