import {useState} from 'react';
import {Cable} from 'lucide-react';
import UiSelect from './UiSelect.jsx';
import {allohaMode,setAllohaMode,ALLOHA_MODE_VERSION} from './alloha-connector.js';

export default function AllohaConnection({service}){
 const [mode,setMode]=useState(allohaMode),[error,setError]=useState('');
 if(Number(service.session?.serverVersion)<ALLOHA_MODE_VERSION||!service.session?.serverVersion)return null;
 function change(value){
  try{setAllohaMode(value);setMode(value);setError('');}
  catch{setError('Браузер не разрешил сохранить настройку.');}
 }
 return <section className="settings-card">
  <div className="section-heading"><h2><Cable size={19}/> Alloha</h2></div>
  <label className="form-field input-label">Способ подключения
   <UiSelect className="field-input" value={mode} onValueChange={change}>
    <option value="browser">Серверная сессия P6</option>
    <option value="bnsi">Прямой поток (BNSI)</option>
   </UiSelect>
  </label>
  <p className="fine">Настройка действует на этом устройстве для новых сеансов просмотра и заданий сохранения Alloha.</p>
  {error&&<p className="inline-error" role="alert">{error}</p>}
 </section>;
}
