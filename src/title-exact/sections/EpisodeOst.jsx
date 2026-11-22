import {useEffect, useMemo, useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ExternalLink, Play} from 'lucide-react';
import {playMusic} from '../../music-player.js';
import {loadEpisodeOst, ostTrack, spotifyTrackUrl} from '../../use-episode-ost.js';
import {ease, glass, rowScroll} from './ui.jsx';

/* «Саундтрек по сериям» in the design: pick an episode from the capsules, the
   episode runs as a glass timeline with every recognised cue on it, and the
   cues below share its colours; hovering either lights up the other. */
const clock = v => { v = Math.max(0, Math.floor(v || 0)); return Math.floor(v / 60) + ':' + String(v % 60).padStart(2, '0'); };
const hue = text => { let h = 0; for (const c of String(text)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };

export function EpisodeOst({identity, isNoir}) {
  const server = window.MEDIA_VAULT_CONFIG?.importServerUrl, reduce = useReducedMotion();
  const [title, setTitle] = useState(null), [episode, setEpisode] = useState(1), [data, setData] = useState(null), [error, setError] = useState(''), [uncertain, setUncertain] = useState(false), [hover, setHover] = useState(null);
  useEffect(() => {
    setTitle(null);
    if (!/^\d+$/.test(String(identity || '')) || !server) return;
    const abort = new AbortController();
    fetch(server + '/music/ost/' + identity, {signal: AbortSignal.any([abort.signal, AbortSignal.timeout(15000)])}).then(r => r.ok ? r.json() : null)
      .then(v => { if (!abort.signal.aborted && v?.available) { setTitle(v); setEpisode(v.episodes[0]); } }).catch(() => {});
    return () => abort.abort();
  }, [identity, server]);
  useEffect(() => {
    setData(null); setError('');
    if (!title) return;
    const abort = new AbortController();
    loadEpisodeOst(server, identity, episode, AbortSignal.any([abort.signal, AbortSignal.timeout(20000)])).then(v => { if (!abort.signal.aborted) setData(v); }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [title, episode]);
  const tracks = (data?.tracks || []).filter(t => uncertain || !t.uncertain);
  const groups = useMemo(() => {
    const map = new Map();
    for (const t of tracks) { if (!map.has(t.title)) map.set(t.title, {...t, segments: []}); map.get(t.title).segments.push(t); }
    return [...map.values()].sort((a, b) => a.segments[0].start - b.segments[0].start);
  }, [data, uncertain]);
  if (!title) return null;
  const hidden = (data?.tracks || []).filter(t => t.uncertain).length;
  const length = Number(data?.episodeDuration) || Math.max(1, ...(data?.tracks || []).map(t => t.end));
  const queue = groups.map(g => ostTrack(g));
  const accent = isNoir ? 'text-white' : 'text-rose-300';
  const color = (name, alpha = 1) => isNoir ? `hsl(0 0% ${55 + hue(name) % 40}% / ${alpha})` : `hsl(${hue(name)} 72% 62% / ${alpha})`;
  return <div className={`rounded-3xl border p-5 sm:p-7 ${glass(isNoir)}`} translate="no">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className={`text-[11px] uppercase tracking-[0.22em] ${accent}`}>Саундтрек по сериям</p>
        <p className="mt-1 text-2xl font-light text-white">Что звучит в <span className="font-black">{episode}</span> серии</p>
      </div>
      {data && <p className="text-[12px] text-zinc-400 tabular-nums">{groups.length} {groups.length === 1 ? 'мелодия' : [2, 3, 4].includes(groups.length % 10) && ![12, 13, 14].includes(groups.length % 100) ? 'мелодии' : 'мелодий'} · {clock(length)}</p>}
    </div>
    <div className={`mt-5 flex gap-1.5 ${rowScroll}`} role="tablist" aria-label="Серия">
      {title.episodes.map(n => <button key={n} type="button" role="tab" aria-selected={n === episode} onClick={() => setEpisode(n)}
        className={`shrink-0 snap-start min-w-[42px] h-9 px-3 rounded-full border text-[12px] font-semibold tabular-nums transition-all duration-300 ${n === episode
          ? (isNoir ? 'bg-white text-black border-white' : 'bg-gradient-to-b from-rose-500/60 to-rose-700/45 text-white border-rose-300/35 shadow-[inset_0_1px_0_rgba(255,255,255,0.28),0_10px_26px_-8px_rgba(225,29,72,0.65)]')
          : 'bg-white/[0.04] border-white/[0.07] text-zinc-300 hover:text-white hover:border-white/20 hover:-translate-y-0.5'}`}>{n}</button>)}
    </div>
    {error ? <p className="mt-5 text-[13px] text-zinc-400" role="alert">{error}</p> : !data ? <p className="mt-5 text-[13px] text-zinc-400" role="status">Загружаем музыку {episode} серии…</p> : <>
      {/* The episode as a timeline: every cue where it plays. */}
      <div className="mt-6">
        <div className="relative h-12 rounded-2xl bg-white/[0.035] border border-white/[0.06] overflow-hidden" aria-hidden="true">
          {tracks.map(t => <span key={t.title + t.start} title={t.title + ' · ' + clock(t.start) + '–' + clock(t.end)} onMouseEnter={() => setHover(t.title)} onMouseLeave={() => setHover(null)}
            className="absolute top-2 bottom-2 rounded-lg transition-[opacity,transform] duration-300"
            style={{left: t.start / length * 100 + '%', width: Math.max(.6, (t.end - t.start) / length * 100) + '%', background: `linear-gradient(to bottom, ${color(t.title, .95)}, ${color(t.title, .55)})`,
              opacity: hover && hover !== t.title ? .25 : t.uncertain ? .45 : 1, transform: hover === t.title ? 'scaleY(1.18)' : 'none', boxShadow: hover === t.title ? `0 0 18px ${color(t.title, .6)}` : 'none'}}/>)}
        </div>
        <div className="relative h-5 mt-1.5">{[0, .25, .5, .75, 1].map(f => <small key={f} className="absolute top-0 -translate-x-1/2 font-mono text-[10px] text-zinc-500 first:translate-x-0 last:-translate-x-full" style={{left: f * 100 + '%'}}>{clock(f * length)}</small>)}</div>
      </div>
      <ul className="mt-4 grid md:grid-cols-2 gap-2.5">
        <AnimatePresence initial={false} mode="popLayout">{groups.map((g, i) => <motion.li key={episode + ':' + g.title} initial={reduce ? false : {opacity: 0, y: 10}} animate={{opacity: 1, y: 0}} exit={{opacity: 0}} transition={{duration: .35, ease, delay: Math.min(i, 8) * .04}}
          onMouseEnter={() => setHover(g.title)} onMouseLeave={() => setHover(null)}
          className={`group flex items-center gap-4 pl-3 pr-2.5 py-3 rounded-2xl border transition-colors duration-300 ${hover === g.title ? 'bg-white/[0.06] border-white/15' : 'bg-white/[0.02] border-white/[0.06]'}`}>
          <span className="w-1 self-stretch rounded-full shrink-0" style={{background: color(g.title)}}/>
          <span className="flex-1 min-w-0">
            <strong className="block truncate text-[14px] font-bold text-white" title={g.title}>{g.title}</strong>
            <small className="block truncate text-[11px] text-zinc-400 mt-0.5">{g.album || 'Саундтрек'}{g.segments.some(s => s.uncertain) ? ' · неуверенно' : ''}</small>
            <span className="mt-1.5 flex flex-wrap gap-1">{g.segments.map(s => <em key={s.start} className="not-italic px-2 py-0.5 rounded-full bg-white/[0.05] font-mono text-[10px] text-zinc-300">{clock(s.start)}–{clock(s.end)}</em>)}</span>
          </span>
          <span className="flex items-center gap-1.5 shrink-0">
            {spotifyTrackUrl(g.spotify) && <a href={spotifyTrackUrl(g.spotify)} target="_blank" rel="noopener noreferrer" aria-label={'Официальный трек в Spotify: ' + g.title} title="Официальный трек в Spotify"
              className="w-9 h-9 grid place-items-center rounded-full bg-white/[0.05] border border-white/[0.1] text-zinc-300 hover:text-white"><ExternalLink size={14}/></a>}
            <button type="button" aria-label={'Слушать ' + g.title} title="Слушать" onClick={() => playMusic(ostTrack(g), queue)}
              className={`w-9 h-9 grid place-items-center rounded-full transition-transform group-hover:scale-105 ${isNoir ? 'bg-white text-black' : 'bg-rose-600 hover:bg-rose-500 text-white shadow-[0_0_18px_rgba(225,29,72,0.45)]'}`}><Play size={13} fill="currentColor" strokeWidth={0} className="ml-px"/></button>
          </span>
        </motion.li>)}</AnimatePresence>
      </ul>
      {!groups.length && <p className="mt-4 text-[13px] text-zinc-400">В этой серии уверенных совпадений нет.</p>}
      {hidden > 0 && <button type="button" onClick={() => setUncertain(v => !v)} className="mt-4 text-[12px] text-zinc-400 hover:text-white underline underline-offset-4 decoration-white/20">{uncertain ? 'Скрыть неуверенные совпадения' : 'Показать неуверенные совпадения · ' + hidden}</button>}
    </>}
    <p className="mt-5 text-[11px] text-zinc-500">Данные: <a href={data?.url || title.url} target="_blank" rel="noopener noreferrer" className="hover:text-white underline underline-offset-2 decoration-white/20">WTAS.moe</a> — автоматическое распознавание музыки, время приблизительное и возможны ошибки.{title.albums?.length > 0 && <> Альбомы: {title.albums.map((a, i) => <span key={a.url}>{i ? ', ' : ''}<a href={a.url} target="_blank" rel="noopener noreferrer" className="hover:text-white">{a.name}</a></span>)}.</>}</p>
  </div>;
}
