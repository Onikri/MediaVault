import {useMemo, useRef, useState} from 'react';
import {ArrowUpRight} from 'lucide-react';
import {loadPerson} from '../../title-metadata.js';
import {Dossier} from './Characters.jsx';
import {SectionFrame, Switch, glass, useEntered} from './ui.jsx';
import Panorama from './Panorama.jsx';

/* Создатели: the crew in one snapping row of tall cards, split by craft.
   A photo makes a portrait card; without one the card is set in type (no
   placeholder face). A card opens the same glass dossier as the characters. */
const CRAFTS = [
  ['direction', 'Режиссура', /режисс|director|раскадров|storyboard|постанов/i],
  ['story', 'Сюжет', /автор|сценар|оригинал|script|story|composition|creator|писател|сериал/i],
  ['art', 'Художники', /художн|дизайн|анимац|animat|art|design|цвет|color|фон|background|ключ/i],
  ['music', 'Музыка', /музык|music|звук|sound|композит/i],
  ['voice', 'Сэйю', /сэйю|сейю|seiyuu|voice/i],
  ['production', 'Продюсеры', /продюс|produc|производ/i]
];
const craftOf = role => CRAFTS.find(([, , test]) => test.test(role || ''))?.[0] || 'other';

export function CreatorsSection({k, isNoir, profile, server, kind = 'anime', renderArtwork}) {
  const people = useMemo(() => {
    const all = [...(profile.staff || []), ...(profile.characters || []).flatMap(c => (c.voiceActors || []).map(v => ({...v, role: 'Сэйю · ' + c.name})))];
    // One card per person: several duties are joined into one line.
    const byId = new Map();
    for (const p of all) {
      const key = String(p.id ?? p.name), old = byId.get(key);
      if (old) { if (!old.roles.includes(p.role)) old.roles.push(p.role); }
      else byId.set(key, {...p, roles: [p.role].filter(Boolean)});
    }
    return [...byId.values()].map(p => ({...p, role: p.roles.join(' · '), crafts: [...new Set(p.roles.map(craftOf))]}));
  }, [profile.staff, profile.characters]);
  const crafts = useMemo(() => CRAFTS.filter(([id]) => people.some(p => p.crafts.includes(id))), [people]);
  const [craft, setCraft] = useState('all'), [person, setPerson] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const origin = useRef(null), generation = useRef(0), [ref, entered] = useEntered();
  const shown = craft === 'all' ? people : people.filter(p => p.crafts.includes(craft));
  async function open(value, trigger) {
    if (trigger) origin.current = trigger;
    const current = ++generation.current;
    setPerson(value); setError(''); setBusy(true);
    try {
      const detail = await loadPerson(value.id, {server});
      if (current !== generation.current) return;
      setPerson({...value, ...detail, role: value.role});
      if (server && !detail.description) fetch(server + '/metadata/anime-browse?' + new URLSearchParams({kind: 'person', identity: value.id, label: value.name}))
        .then(r => r.ok ? r.json() : {}).then(d => { if (current === generation.current && d.entity) setPerson(old => ({...old, description: d.entity.description, facts: d.entity.facts, bioSource: d.entity.sourceUrl, license: d.entity.license})); }).catch(() => {});
    } catch (cause) { if (current === generation.current) setError(cause.message); }
    finally { if (current === generation.current) setBusy(false); }
  }
  if (!people.length) return null;
  const accent = isNoir ? 'text-zinc-300' : 'text-rose-200/80';
  return <SectionFrame>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-[13px] text-zinc-400">{people.length} в съёмочной группе · нажми на карточку, чтобы открыть досье</p>
      {crafts.length > 1 && <Switch label="Профессия" value={craft} onChange={setCraft} isNoir={isNoir} options={[['all', 'Все'], ...crafts.map(([id, name]) => [id, name])]}/>}
    </div>
    <div ref={ref} key={craft}>
      <Panorama items={shown} idOf={p => String(p.id ?? p.name)} k={k} isNoir={isNoir} label="Съёмочная группа" mapLabel="Карта группы"
        renderCard={(p, idx) => <button type="button" onClick={e => open(p, e.currentTarget)} aria-label={'Создатель: ' + p.name}
          className={`group relative block w-full aspect-[3/4] rounded-[22px] overflow-hidden border text-left transition-[transform,box-shadow,border-color,opacity] duration-700 hover:-translate-y-1.5 ${isNoir ? 'border-white/20 hover:border-white/60' : 'border-white/[0.08] hover:border-rose-300/40 hover:shadow-[0_24px_50px_-22px_rgba(225,29,72,0.55)]'} ${p.image ? '' : glass(isNoir)} ${entered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
          style={{transitionDelay: entered ? `${Math.min(idx, 12) * 45}ms` : '0ms'}}>
          {p.image ? <>
            <span className={`absolute inset-0 kt-cover kt-top transition-transform duration-700 ease-out group-hover:scale-[1.07] ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(p)}</span>
            <span className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent"/>
          </> : <span aria-hidden="true" className="absolute inset-x-3.5 top-3.5 text-[30px] leading-[0.9] font-black tracking-tighter text-white/[0.07] break-words transition-colors duration-500 group-hover:text-white/[0.12]">{p.name}</span>}
          <span className="absolute inset-x-3.5 bottom-3.5">
            <span className={`block text-[9px] uppercase tracking-[0.14em] line-clamp-2 ${accent}`}>{p.role}</span>
            <span className="block mt-1 text-[15px] font-black tracking-tight text-white leading-tight line-clamp-2">{p.name}</span>
          </span>
          <span className="absolute top-3 right-3 w-7 h-7 grid place-items-center rounded-full bg-black/45 border border-white/15 text-white opacity-0 -translate-y-1 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-300"><ArrowUpRight size={13}/></span>
        </button>}
        renderMini={p => p.image ? <>
          <span className={`absolute inset-0 kt-cover kt-top transition-transform duration-500 group-hover:scale-110 ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(p)}</span>
          <span className="absolute inset-0 bg-gradient-to-t from-black/85 via-transparent to-transparent"/>
          <span className="absolute inset-x-2 bottom-1.5 text-[10px] font-bold leading-tight text-white line-clamp-2">{p.name}</span>
        </> : <span className={`absolute inset-0 flex items-end p-2 ${glass(isNoir)}`}><span className="text-[10px] font-bold leading-tight text-white line-clamp-3">{p.name}</span></span>}/>
    </div>
    {person && <Dossier kind="person" characters={shown.length ? shown : people} character={person} busy={busy} error={error} origin={origin.current} isNoir={isNoir}
      onPick={value => open(value)} onClose={() => { generation.current++; setPerson(null); origin.current?.isConnected && origin.current.focus({preventScroll: true}); }} renderArtwork={renderArtwork}/>}
  </SectionFrame>;
}
