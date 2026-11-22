import {useEffect, useMemo, useRef, useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ChevronLeft, ChevronRight, ExternalLink, Play} from 'lucide-react';
import {playMusic} from '../../music-player.js';
import {loadEpisodeOst, ostTrack, spotifyTrackUrl} from '../../use-episode-ost.js';
import {ease, glass} from './ui.jsx';

/* «Саундтрек по сериям», minimal: one header line with the episode stepper,
   a hairline timeline of the episode with every cue on it, and a dense grid of
   small cue rows; hovering either side lights up the other. */
const clock = v => { v = Math.max(0, Math.floor(v || 0)); return Math.floor(v / 60) + ':' + String(v % 60).padStart(2, '0'); };
const hue = text => { let h = 0; for (const c of String(text)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const plural = n => n % 10 === 1 && n % 100 !== 11 ? 'мелодия' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'мелодии' : 'мелодий';

export function EpisodeOst({identity, isNoir}) {
  const server = window.MEDIA_VAULT_CONFIG?.importServerUrl, reduce = useReducedMotion();
  const [title, setTitle] = useState(null), [episode, setEpisode] = useState(1), [data, setData] = useState(null), [error, setError] = useState(''), [uncertain, setUncertain] = useState(false), [hover, setHover] = useState(null);
  const strip = useRef(null);
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
  useEffect(() => { strip.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({block: 'nearest', inline: 'center', behavior: reduce ? 'auto' : 'smooth'}); }, [episode, title]);
  const tracks = (data?.tracks || []).filter(t => uncertain || !t.uncertain);
  const groups = useMemo(() => {
    const map = new Map();
    for (const t of tracks) { if (!map.has(t.title)) map.set(t.title, {...t, segments: []}); map.get(t.title).segments.push(t); }
    return [...map.values()].sort((a, b) => a.segments[0].start - b.segments[0].start);
  }, [data, uncertain]);
  if (!title) return null;
  const episodes = title.episodes, at = episodes.indexOf(episode);
  const hidden = (data?.tracks || []).filter(t => t.uncertain).length;
  const length = Number(data?.episodeDuration) || Math.max(1, ...(data?.tracks || []).map(t => t.end));
  const queue = groups.map(g => ostTrack(g));
  const color = (name, alpha = 1) => isNoir ? `hsl(0 0% ${55 + hue(name) % 40}% / ${alpha})` : `hsl(${hue(name)} 72% 62% / ${alpha})`;
  const step = d => { const next = episodes[at + d]; if (next != null) setEpisode(next); };
  const arrow = 'grid place-items-center w-7 h-7 shrink-0 rounded-full text-zinc-400 hover:text-white hover:bg-white/10 disabled:opacity-25 transition-colors';
  const hovered = groups.find(g => g.title === hover);
  return <div className={`rounded-[22px] border p-4 ${glass(isNoir)}`} translate="no">
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <p className="flex items-baseline gap-2.5 min-w-0">
        <span className={`text-[10px] uppercase tracking-[0.2em] ${isNoir ? 'text-white' : 'text-rose-300'}`}>Саундтрек по сериям</span>
        <span className="text-[12px] text-zinc-400 tabular-nums truncate">серия <b className="text-white font-bold">{episode}</b>{data ? ` · ${groups.length} ${plural(groups.length)} · ${clock(length)}` : ''}</span>
      </p>
      <div className="flex items-center gap-1 min-w-0 max-w-full sm:max-w-[55%]">
        <button type="button" className={arrow} aria-label="Предыдущая серия" disabled={at <= 0} onClick={() => step(-1)}><ChevronLeft size={14}/></button>
        <div ref={strip} className="flex gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" role="tablist" aria-label="Серия">
          {episodes.map(n => <button key={n} type="button" role="tab" aria-selected={n === episode} onClick={() => setEpisode(n)}
            className={`shrink-0 min-w-[28px] h-7 px-2 rounded-full text-[11px] font-semibold tabular-nums transition-colors ${n === episode ? (isNoir ? 'bg-white text-black' : 'bg-rose-600 text-white') : 'text-zinc-400 hover:text-white hover:bg-white/[0.07]'}`}>{n}</button>)}
        </div>
        <button type="button" className={arrow} aria-label="Следующая серия" disabled={at < 0 || at >= episodes.length - 1} onClick={() => step(1)}><ChevronRight size={14}/></button>
      </div>
    </div>
    {error ? <p className="mt-3 text-[12px] text-zinc-400" role="alert">{error}</p> : !data ? <p className="mt-3 text-[12px] text-zinc-400" role="status">Загружаем музыку {episode} серии…</p> : <>
      {/* The episode as a hairline: every cue where it plays. */}
      <div className="relative mt-4 pt-5">
        <AnimatePresence>{hovered && <motion.span key={hovered.title} initial={{opacity: 0, y: 4}} animate={{opacity: 1, y: 0}} exit={{opacity: 0}} transition={{duration: .15}}
          className="absolute top-0 -translate-x-1/2 px-2 py-0.5 rounded-full bg-black/80 border border-white/10 text-[10px] text-white whitespace-nowrap pointer-events-none"
          style={{left: `clamp(60px, ${hovered.segments[0].start / length * 100}%, calc(100% - 60px))`}}>{hovered.title} · {clock(hovered.segments[0].start)}</motion.span>}</AnimatePresence>
        <div className="relative h-2 rounded-full bg-white/[0.06]" aria-hidden="true">
          {tracks.map(t => <span key={t.title + t.start} onMouseEnter={() => setHover(t.title)} onMouseLeave={() => setHover(null)}
            className="absolute inset-y-0 rounded-full transition-[opacity,transform] duration-200"
            style={{left: t.start / length * 100 + '%', width: Math.max(.5, (t.end - t.start) / length * 100) + '%', background: color(t.title), opacity: hover && hover !== t.title ? .2 : t.uncertain ? .45 : .9, transform: hover === t.title ? 'scaleY(1.8)' : 'none'}}/>)}
        </div>
        <div className="mt-1 flex justify-between font-mono text-[9px] text-zinc-600">{[0, .25, .5, .75, 1].map(f => <span key={f}>{clock(f * length)}</span>)}</div>
      </div>
      <ul className="mt-3 grid sm:grid-cols-2 xl:grid-cols-3 gap-1.5">
        <AnimatePresence initial={false} mode="popLayout">{groups.map((g, i) => <motion.li key={episode + ':' + g.title} initial={reduce ? false : {opacity: 0, y: 6}} animate={{opacity: 1, y: 0}} exit={{opacity: 0}} transition={{duration: .3, ease, delay: Math.min(i, 12) * .025}}
          onMouseEnter={() => setHover(g.title)} onMouseLeave={() => setHover(null)}
          className={`group flex items-center gap-2.5 h-11 pl-2.5 pr-1.5 rounded-xl transition-colors duration-200 ${hover === g.title ? 'bg-white/[0.07]' : 'bg-white/[0.02] hover:bg-white/[0.05]'}`}>
          <span className="w-[3px] h-5 rounded-full shrink-0" style={{background: color(g.title)}}/>
          <span className="flex-1 min-w-0">
            <strong className="block truncate text-[12px] font-semibold text-white" title={g.title + (g.album ? ' · ' + g.album : '')}>{g.title}</strong>
            <small className="block truncate font-mono text-[9px] text-zinc-500">{g.segments.map(s => clock(s.start) + '–' + clock(s.end)).join('  ')}{g.segments.some(s => s.uncertain) ? ' · неуверенно' : ''}</small>
          </span>
          {spotifyTrackUrl(g.spotify) && <a href={spotifyTrackUrl(g.spotify)} target="_blank" rel="noopener noreferrer" aria-label={'Официальный трек в Spotify: ' + g.title} title="Официальный трек в Spotify"
            className="grid place-items-center w-7 h-7 shrink-0 rounded-full text-zinc-500 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-white hover:bg-white/10 transition-opacity"><ExternalLink size={12}/></a>}
          <button type="button" aria-label={'Слушать ' + g.title} title="Слушать" onClick={() => playMusic(ostTrack(g), queue)}
            className={`grid place-items-center w-7 h-7 shrink-0 rounded-full transition-transform group-hover:scale-110 ${isNoir ? 'bg-white text-black' : 'bg-rose-600 text-white'}`}><Play size={11} fill="currentColor" strokeWidth={0} className="ml-px"/></button>
        </motion.li>)}</AnimatePresence>
      </ul>
      {!groups.length && <p className="mt-3 text-[12px] text-zinc-400">В этой серии уверенных совпадений нет.</p>}
    </>}
    <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-zinc-500">
      {hidden > 0 && <button type="button" onClick={() => setUncertain(v => !v)} className="text-zinc-400 hover:text-white underline underline-offset-4 decoration-white/20">{uncertain ? 'Скрыть неуверенные' : 'Неуверенные совпадения · ' + hidden}</button>}
      <span>Данные: <a href={data?.url || title.url} target="_blank" rel="noopener noreferrer" className="hover:text-white underline underline-offset-2 decoration-white/20">WTAS.moe</a> — автоматическое распознавание, время приблизительное.</span>
      {title.albums?.length > 0 && <span>Альбомы: {title.albums.map((a, i) => <span key={a.url}>{i ? ', ' : ''}<a href={a.url} target="_blank" rel="noopener noreferrer" className="hover:text-white">{a.name}</a></span>)}</span>}
    </p>
  </div>;
}
