import {useState} from 'react';
import {X} from 'lucide-react';

// Several tags narrow the catalogue together: a title must carry all of them.
// The value stays the comma-joined string the catalogue APIs already accept.
const LIMIT=12;
export const splitTags=value=>String(value||'').split(',').map(tag=>tag.trim()).filter(Boolean);

export default function CatalogTagPicker({value,options=[],onChange}){
 const tags=splitTags(value),[draft,setDraft]=useState('');
 const known=new Map(options.map(option=>[option.toLocaleLowerCase(),option]));
 const has=tag=>tags.some(old=>old.toLocaleLowerCase()===tag.toLocaleLowerCase());
 const add=raw=>{
  const tag=(known.get(raw.trim().toLocaleLowerCase())||raw.trim()).replace(/,/g,' ').trim();
  setDraft('');
  if(!tag||has(tag)||tags.length>=LIMIT)return;
  onChange([...tags,tag].join(','));
 };
 const remove=tag=>onChange(tags.filter(old=>old!==tag).join(','));
 const type=event=>{
  const next=event.target.value;
  // Picking a suggestion fills the whole name at once; add it right away.
  if(known.has(next.trim().toLocaleLowerCase())&&next.length-draft.length>1){add(next);return;}
  if(next.includes(',')){add(next.replace(/,/g,''));return;}
  setDraft(next);
 };
 const key=event=>{
  if(event.key==='Enter'&&draft.trim()){event.preventDefault();add(draft);}
  else if(event.key==='Backspace'&&!draft&&tags.length)remove(tags[tags.length-1]);
 };
 return <div className="catalog-tag-picker">
  <label className={tags.length?'is-set':undefined}>Теги<input className="field-input" value={draft} onChange={type} onKeyDown={key} onBlur={()=>draft.trim()&&known.has(draft.trim().toLocaleLowerCase())&&add(draft)} list="catalogTags" disabled={tags.length>=LIMIT} placeholder={tags.length>=LIMIT?'Не больше 12 тегов':tags.length?'Добавить ещё':'Например, магия'} aria-describedby={tags.length?'catalogTagChips':undefined}/>
   <datalist id="catalogTags">{options.filter(option=>!has(option)).map(option=><option key={option} value={option}/>)}</datalist>
  </label>
  {tags.length>0&&<ul id="catalogTagChips" className="tag-chips" aria-label="Выбранные теги">{tags.map(tag=><li key={tag}><span>{tag}</span><button type="button" aria-label={'Убрать тег '+tag} onClick={()=>remove(tag)}><X size={12}/></button></li>)}</ul>}
 </div>;
}
