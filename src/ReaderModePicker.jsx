import {GalleryHorizontalEnd,BookOpen,Scan,ScrollText} from 'lucide-react';
import './reader-morph.css';
const modes=[['pages','По страницам'],['focus','Вписать целиком'],['spread','Разворот'],['scroll','Вебтун']];
const icons={pages:GalleryHorizontalEnd,focus:Scan,spread:BookOpen,scroll:ScrollText};
// Lucide's open-source reading symbols. No perpetual decorative icon animation.
export function ReaderModeIcon({mode}){const Icon=icons[mode]||BookOpen;return <Icon size={25} strokeWidth={1.4} aria-hidden="true"/>;}
// unavailable: {mode: reason} — a mode this chapter cannot show, with why.
export default function ReaderModePicker({value,onChange,compact=false,unavailable={}}){return <div className={'reader-mode-picker'+(compact?' is-compact':'')} role="group" aria-label="Режим чтения">{modes.map(([id,label])=><button key={id} aria-label={label} title={unavailable[id]||label} disabled={!!unavailable[id]} aria-pressed={value===id} onClick={()=>onChange(id)}><ReaderModeIcon mode={id}/>{!compact&&<span>{label}</span>}</button>)}</div>;}
