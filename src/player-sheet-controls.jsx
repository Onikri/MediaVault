import {Check,ChevronRight} from 'lucide-react';

// Building blocks of the player settings sheet. State is shown by tone, not borders.
export function Row({label,value,onClick,disabled,hint}){
  const text=<span className="mvx-row-text"><span>{label}</span>{hint&&<small>{hint}</small>}</span>;
  if(!onClick||disabled)return <div className="mvx-row is-static">{text}<span className="mvx-row-value">{value}</span></div>;
  return <button type="button" className="mvx-row" onClick={onClick}>{text}<span className="mvx-row-value">{value}</span><ChevronRight size={16} aria-hidden="true"/></button>;
}

export function Switch({label,hint,checked,onChange,disabled}){
  return <button type="button" className="mvx-row mvx-switch-row" role="switch" aria-checked={!!checked} disabled={disabled} onClick={()=>onChange(!checked)}>
    <span className="mvx-row-text"><span>{label}</span>{hint&&<small>{hint}</small>}</span><span className="mvx-switch" aria-hidden="true"><i/></span>
  </button>;
}

export function Choices({label,options,value,onPick}){
  return <div className="mvx-choices" role="radiogroup" aria-label={label}>
    {options.map(option=>{
      const checked=String(option.value)===String(value);
      return <button type="button" key={option.value} role="radio" aria-checked={checked} className="mvx-choice" disabled={option.disabled} onClick={()=>onPick(option.value)}>
        <span><strong>{option.label}{option.badges}</strong>{option.hint&&<small>{option.hint}</small>}</span>
        {checked&&<Check size={16} aria-hidden="true"/>}
      </button>;
    })}
  </div>;
}

export function Segmented({label,options,value,onPick}){
  return <div className="mvx-field"><span className="mvx-field-label">{label}</span>
    <div className="mvx-segmented" role="radiogroup" aria-label={label}>
      {options.map(option=><button type="button" key={option.value} role="radio" aria-checked={String(option.value)===String(value)} onClick={()=>onPick(option.value)}>{option.label}</button>)}
    </div>
  </div>;
}

export function Slider({label,ariaLabel,min,max,step,value,format,onChange}){
  const fill=Math.max(0,Math.min(100,(value-min)/(max-min)*100));
  return <label className="mvx-slider">
    <span className="mvx-slider-label">{label}</span>
    <input type="range" aria-label={ariaLabel||label} min={min} max={max} step={step} value={value} style={{'--fill':fill+'%'}} onChange={event=>onChange(Number(event.target.value))}/>
    <output>{format(value)}</output>
  </label>;
}

export function Note({children,role}){return <p className="mvx-help" role={role}>{children}</p>;}
export function Group({children}){return <div className="mvx-group">{children}</div>;}
