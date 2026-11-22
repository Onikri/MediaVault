import { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { KineticItem } from './kinetic.jsx';

/* The design's own section blocks, filled with the real title: tall portrait
   character cards, related works with their covers and the episode capsules
   of a library title. `k` carries sectionIndex and enabled for the kinetics. */

const GLASS = 'bg-gradient-to-b from-white/[0.06] to-white/[0.015] border-white/[0.07] shadow-[inset_0_1px_0_rgba(255,255,255,0.07)]';
const GLASS_NOIR = 'bg-gradient-to-b from-white/[0.08] to-white/[0.02] border-white/20 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]';
const card = (isNoir) => (isNoir ? GLASS_NOIR + ' hover:border-white/50' : GLASS + ' hover:border-rose-400/30');

export function CharactersRow({ k, isNoir, characters, limit, onMore, onOpen, renderImage, emptyNote }) {
  if (!characters?.length) return <p className="text-[13px] text-zinc-400">{emptyNote}</p>;
  const shown = characters.slice(0, limit);
  return <div className="space-y-5" translate="no">
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {shown.map((c, idx) => <KineticItem key={c.id || c.name} weight={0.8 + (idx % 4) * 0.12} drift={((idx % 4) - 1.5) * 0.6} {...k}>
        <button type="button" onClick={(event) => onOpen(c, event.currentTarget)}
          className={`group relative block w-full aspect-[2/3] rounded-3xl overflow-hidden border text-left transition-[transform,box-shadow,border-color] duration-500 hover:-translate-y-1.5 ${isNoir ? 'border-white/20 hover:border-white/60' : 'border-white/[0.08] hover:border-rose-300/40 hover:shadow-[0_28px_60px_-24px_rgba(225,29,72,0.55)]'}`}>
          <span className={`absolute inset-0 kt-cover transition-transform duration-700 ease-out group-hover:scale-[1.06] ${isNoir ? 'grayscale' : ''}`}>{renderImage(c)}</span>
          <span className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/25 to-black/10" />
          <span className="absolute inset-0 rounded-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] pointer-events-none" />
          {c.role && <span className="absolute top-4 left-4 px-2.5 py-1 rounded-full bg-black/30 backdrop-blur-md border border-white/15 text-[10px] uppercase tracking-[0.16em] text-white/90">{c.role}</span>}
          <span className="absolute inset-x-5 bottom-5">
            <span className="block text-lg sm:text-xl font-black tracking-tight text-white leading-tight">{c.name}</span>
            {c.voice && <span className={`block mt-1.5 text-[11px] ${isNoir ? 'text-zinc-300' : 'text-rose-200/80'}`}>Сэйю · {c.voice}</span>}
          </span>
        </button>
      </KineticItem>)}
    </div>
    {characters.length > limit && <KineticItem weight={0.9} {...k}>
      <button type="button" onClick={onMore}
        className={`px-5 py-2.5 rounded-full border backdrop-blur-md text-[12px] font-medium text-zinc-200 hover:text-white transition-colors ${card(isNoir)}`}>
        Ещё персонажи · {characters.length - limit}
      </button>
    </KineticItem>}
  </div>;
}

export function RelatedCards({ k, isNoir, related, onOpen, renderImage }) {
  return <div className="grid grid-cols-1 md:grid-cols-3 gap-4" translate="no">
    {related.map((w, idx) => <KineticItem key={w.kind + w.id} weight={0.75 + (idx % 3) * 0.3} drift={(idx % 3) - 1} {...k} className="h-full">
      <button type="button" onClick={() => onOpen(w)}
        className={`group h-full w-full p-6 rounded-3xl border flex flex-col justify-between gap-6 text-left transition-colors ${card(isNoir)}`}>
        <span className="flex items-start justify-between gap-3">
          <span className="space-y-2">
            {w.format && <span className={`inline-block px-3 py-1 rounded-full text-[11px] font-semibold border ${isNoir ? 'bg-white/10 text-white border-white/25' : 'bg-rose-500/20 text-rose-300 border-rose-500/30'}`}>{w.format}</span>}
            {w.relation && <span className="block text-[10px] uppercase tracking-[0.18em] text-zinc-500">{w.relation}</span>}
          </span>
          <span className={`relative w-12 aspect-[2/3] rounded-lg overflow-hidden shrink-0 border border-white/10 kt-cover transition-transform duration-500 group-hover:-rotate-3 group-hover:scale-105 ${isNoir ? 'grayscale' : ''}`}>{renderImage(w)}</span>
        </span>
        <span>
          <span className="block text-base font-bold text-white leading-snug">{w.title}</span>
          <span className="flex items-center justify-between mt-2 text-xs text-zinc-400">{[w.year, w.kindLabel].filter(Boolean).join(' · ')}<ArrowUpRight size={14} className="text-zinc-500 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-white" /></span>
        </span>
      </button>
    </KineticItem>)}
  </div>;
}

/** A library title's episodes or chapters as one kinetic row of glass capsules. */
export function EpisodeCapsules({ k, items, activeId, unit, label, onPick, parts, part, onPart }) {
  return <div className="space-y-4">
    {parts?.length > 1 && <select aria-label="Сезон или том" value={part} onChange={(e) => onPart(e.target.value)}
      className="px-4 py-2 rounded-full bg-white/[0.06] border border-white/[0.1] text-[12px] text-white">
      {parts.map((v) => <option key={v.name}>{v.name}</option>)}
    </select>}
    <KineticItem weight={0.85} {...k}>
      <div className="kt-capsules" role="group" aria-label={label}>
        {items.map((item, index) => <button key={item.id} type="button" className="kt-capsule" aria-pressed={item.id === activeId}
          aria-label={item.title} title={item.detail || item.title} onClick={() => onPick(item.source)}>
          {item.number ?? index + 1} {unit}
        </button>)}
      </div>
    </KineticItem>
  </div>;
}
