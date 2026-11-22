import {useMemo, useRef, useState} from 'react';
import {ArrowUpRight} from 'lucide-react';
import {loadPerson} from '../../title-metadata.js';
import {KineticItem} from '../kinetic.jsx';
import {Dossier} from './Characters.jsx';
import {SectionFrame, Switch, glass, rowScroll, useEntered} from './ui.jsx';

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
    <div ref={ref} key={craft} translate="no" className={`grid grid-flow-col auto-cols-[calc((100%-16px)/2)] md:auto-cols-[calc((100%-32px)/3)] lg:auto-cols-[calc((100%-64px)/5)] gap-4 -mb-3 ${rowScroll}`}>
      {shown.map((p, idx) => <KineticItem key={p.id ?? p.name} weight={0.8 + (idx % 3) * 0.14} drift={(idx % 3) - 1} {...k}>
        <button type="button" onClick={e => open(p, e.currentTarget)} aria-label={'Создатель: ' + p.name}
          className={`group relative block w-full aspect-[3/4] snap-start rounded-3xl overflow-hidden border text-left transition-[transform,box-shadow,border-color,opacity] duration-700 hover:-translate-y-2 ${isNoir ? 'border-white/20 hover:border-white/60' : 'border-white/[0.08] hover:border-rose-300/40 hover:shadow-[0_28px_60px_-24px_rgba(225,29,72,0.55)]'} ${p.image ? '' : glass(isNoir)} ${entered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-10'}`}
          style={{transitionDelay: entered ? `${Math.min(idx, 8) * 60}ms` : '0ms'}}>
          {p.image ? <>
            <span className={`absolute inset-0 kt-cover kt-top transition-transform duration-700 ease-out group-hover:scale-[1.07] ${isNoir ? 'grayscale' : ''}`}>{renderArtwork(p)}</span>
            <span className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/25 to-transparent"/>
          </> : <span aria-hidden="true" className="absolute inset-x-4 top-4 text-[44px] leading-[0.9] font-black tracking-tighter text-white/[0.06] break-words transition-colors duration-500 group-hover:text-white/[0.1]">{p.name}</span>}
          <span className="absolute inset-0 rounded-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] pointer-events-none"/>
          <span className="absolute inset-x-4 bottom-4">
            <span className={`block text-[10px] uppercase tracking-[0.16em] line-clamp-2 ${accent}`}>{p.role}</span>
            <span className="block mt-1.5 text-base sm:text-lg font-black tracking-tight text-white leading-tight">{p.name}</span>
            <span className="mt-2 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-white/0 group-hover:text-white/80 transition-colors duration-500">Досье <ArrowUpRight size={12}/></span>
          </span>
        </button>
      </KineticItem>)}
    </div>
    {person && <Dossier kind="person" characters={shown.length ? shown : people} character={person} busy={busy} error={error} origin={origin.current} isNoir={isNoir}
      onPick={value => open(value)} onClose={() => { generation.current++; setPerson(null); origin.current?.isConnected && origin.current.focus({preventScroll: true}); }} renderArtwork={renderArtwork}/>}
  </SectionFrame>;
}
