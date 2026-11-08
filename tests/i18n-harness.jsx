// Interface language harness: real ControlCenter shell, fixture panels, no server.
import React from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';import '/src/site-layout.css';import '/src/interface-refinement.css';
import {ThemeProvider,AppearanceSettings} from '/src/blossom/ThemeProvider.tsx';
import ControlCenter from '/src/control/ControlCenter.jsx';
import LanguageSettings from '/src/i18n/LanguageSettings.jsx';
import {installI18n} from '/src/i18n/index.js';

const state={user:{given_name:'Рома',name:'Рома',email:'viewer@example.test',sub:'fixture-viewer'},admin:false,catalog:null};
function Harness(){
 return <ThemeProvider><div className="app-shell" data-view="profile"><main className="app-main">
  <ControlCenter state={state} service={{status:'disconnected',request:async()=>{throw Error('offline');}}} initialTab="appearance" onLogout={()=>{}} panels={{
   account:<section className="settings-card"><h2>Профиль</h2><p className="fine" id="content" translate="no">Настройки плеера — название произведения</p></section>,
   appearance:<><LanguageSettings/><AppearanceSettings/></>,
   privacy:<section className="settings-card"><h2>Это устройство</h2><p className="fine" id="composed">Серия 12</p></section>,
  }}/>
 </main></div></ThemeProvider>;
}
installI18n().finally(()=>createRoot(document.getElementById('root')).render(<Harness/>));
