import {useEffect,useState} from 'react';
import {UI_LANGUAGES,uiLanguage,onUiLanguage,setUiLanguage} from './index.js';

export function useUiLanguage(){
 const [value,setValue]=useState(uiLanguage);
 useEffect(()=>onUiLanguage(setValue),[]);
 return value;
}

export default function LanguageSettings(){
 const current=useUiLanguage(),[busy,setBusy]=useState(''),[error,setError]=useState('');
 async function choose(id){
  if(id===current||busy)return;
  setBusy(id);setError('');
  try{await setUiLanguage(id);}catch{setError('Не удалось загрузить перевод интерфейса. Проверь соединение и попробуй ещё раз.');}
  finally{setBusy('');}
 }
 return <section className="settings-card language-settings" aria-label="Язык интерфейса">
  <header className="section-head"><div><p className="section-number">ЯЗЫК</p><h2>Язык интерфейса</h2></div></header>
  <div className="language-choice" role="radiogroup" aria-label="Язык интерфейса">
   {UI_LANGUAGES.map(([id,label])=><button key={id} type="button" role="radio" aria-checked={current===id} aria-busy={busy===id||undefined} disabled={!!busy} lang={id} translate="no" onClick={()=>choose(id)}>{label}</button>)}
  </div>
  {error&&<p role="alert" className="inline-error">{error}</p>}
  <p className="fine">Меняется интерфейс на этом устройстве. Названия, описания и тексты произведений остаются на языке источника.</p>
 </section>;
}
