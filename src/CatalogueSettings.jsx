import UiSwitch from './UiSwitch.jsx';
import {setCatalogueAnnouncements,useCatalogueAnnouncements} from './catalogue-preferences.js';

export default function CatalogueSettings(){
 const checked=useCatalogueAnnouncements();
 return <section className="settings-card">
  <h2>Библиотека</h2>
  <label className="catalogue-announcements">
   <span>Показывать анонсы</span>
   <UiSwitch aria-label="Показывать анонсы" checked={checked} onCheckedChange={setCatalogueAnnouncements}/>
  </label>
 </section>;
}
