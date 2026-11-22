import {useState} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {ExternalLink, Play, X} from 'lucide-react';
import {TrailerVideo} from '../../Trailers.jsx';
import {KineticItem} from '../kinetic.jsx';
import {SectionFrame, ease} from './ui.jsx';

/* Трейлеры: the chosen video large, the others beside it. Play starts our
   player right inside the large frame. */
export function TrailersSection({k, isNoir, profile, server, userId, onPlaybackChange, renderArtwork}) {
  const list = profile.trailers || [], [main, setMain] = useState(0), [playing, setPlaying] = useState(false), reduce = useReducedMotion();
  const t = list[main];
  if (!t) return null;
  const pick = i => { setMain(i); setPlaying(false); onPlaybackChange?.(false); };
  const start = () => { document.querySelectorAll('video.mv-player-media').forEach(v => v.pause()); setPlaying(true); };
  return <SectionFrame>
    <div className={`grid gap-5 ${list.length > 1 ? 'lg:grid-cols-[minmax(0,1fr)_300px]' : ''}`}>
      <KineticItem weight={0.9} {...k}>
        <div className={`relative aspect-video rounded-[28px] overflow-hidden border shadow-2xl bg-black ${isNoir ? 'border-white/25' : 'border-white/[0.09]'}`}>
          {playing ? <div className="absolute inset-0 [&_.trailer-preparation]:h-full [&_.trailer-preparation]:grid [&_.trailer-preparation]:place-content-center [&_.trailer-preparation]:justify-items-center [&_.trailer-preparation]:gap-3 [&_.trailer-preparation]:text-zinc-400">
            <TrailerVideo key={t.id || t.url} video={t} profile={profile} server={server} userId={userId} onPlaybackChange={onPlaybackChange}/>
            <button type="button" aria-label="Закрыть трейлер" onClick={() => { setPlaying(false); onPlaybackChange?.(false); }} className="absolute top-4 right-4 z-10 w-10 h-10 grid place-items-center rounded-full bg-black/55 backdrop-blur-md border border-white/15 text-white hover:bg-black/75"><X size={17}/></button>
          </div> : <>
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span key={main} className={`absolute inset-0 kt-cover ${isNoir ? 'grayscale' : ''}`} initial={reduce ? false : {opacity: 0, scale: 1.12}} animate={{opacity: 1, scale: 1}} exit={{opacity: 0}} transition={{duration: reduce ? 0 : .8, ease}}>{renderArtwork(t)}</motion.span>
            </AnimatePresence>
            <span className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/10 to-black/40"/>
            <span className="absolute top-5 left-5 px-3 py-1 rounded-full bg-black/55 backdrop-blur-md border border-white/10 text-[11px] font-mono text-zinc-200">{String(main + 1).padStart(2, '0')} / {String(list.length).padStart(2, '0')}</span>
            <button type="button" onClick={start} aria-label={'Смотреть: ' + t.title}
              className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-20 h-20 rounded-full grid place-items-center transition-transform hover:scale-110 ${isNoir ? 'bg-white text-black' : 'bg-rose-600 text-white shadow-[0_0_50px_rgba(225,29,72,0.6)]'}`}>
              <Play size={28} fill="currentColor" className="ml-1"/>
            </button>
            <div className="absolute inset-x-6 bottom-6" translate="no">
              <AnimatePresence mode="wait" initial={false}><motion.p key={main} initial={reduce ? false : {opacity: 0, y: 12}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -8}} transition={{duration: .4, ease}} className="text-2xl sm:text-3xl font-black tracking-tight text-white line-clamp-2">{t.title}</motion.p></AnimatePresence>
              {t.url && <a href={t.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-[12px] text-zinc-400 hover:text-white">Страница ролика<ExternalLink size={11}/></a>}
            </div>
          </>}
        </div>
      </KineticItem>
      {list.length > 1 && <div className="flex lg:flex-col gap-4 overflow-x-auto lg:overflow-x-visible lg:overflow-y-auto lg:max-h-[calc((min(100vw,1520px)-360px)*0.5625)] [scrollbar-width:thin] pb-1">
        {list.map((x, i) => <KineticItem key={x.id || x.url} weight={0.8 + Math.min(i, 4) * 0.12} {...k} className="shrink-0 w-56 lg:w-auto">
          <button type="button" onClick={() => pick(i)} aria-pressed={i === main} translate="no"
            className={`group relative w-full aspect-video rounded-3xl overflow-hidden border text-left transition-all duration-500 ${i === main ? (isNoir ? 'border-white/60' : 'border-rose-400/50 shadow-[0_18px_40px_-18px_rgba(225,29,72,0.6)]') : isNoir ? 'border-white/20 opacity-70 hover:opacity-100' : 'border-white/[0.08] opacity-70 hover:opacity-100'}`}>
            <span className={`absolute inset-0 kt-cover transition-transform duration-700 group-hover:scale-110 ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(x)}</span>
            <span className="absolute inset-0 bg-gradient-to-t from-black/85 to-transparent"/>
            <span className="absolute left-4 right-4 bottom-3"><span className="block text-[13px] font-bold text-white leading-snug line-clamp-2">{x.title}</span><span className="block mt-1 text-[10px] font-mono text-zinc-400">{String(i + 1).padStart(2, '0')}</span></span>
          </button>
        </KineticItem>)}
      </div>}
    </div>
  </SectionFrame>;
}
