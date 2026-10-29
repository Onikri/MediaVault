import React,{useEffect,useState} from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import Icon from './Icons.jsx';
import ReleaseAnnouncements from './ReleaseAnnouncements.jsx';
import CatalogBrowser from './CatalogBrowser.jsx';
import ImportSelection from './ImportSelection.jsx';
import {ImportSettings,ImportQueue,ReleaseCalendar} from './ImportParts.jsx';
import './import-workspace.css';
export default function ServerImport({state,service,onConnect,onOpenLibrary,initialItem,initialQuery,initialKind,destination='drive',embedded=false,hideHeading=false}){
 const [target,setTarget]=useState(destination),[tab,setTab]=useState('catalog'),[items,setItems]=useState([]),online=destination==='online';
 const submitted=()=>setTab('queue');
 useEffect(()=>{if(initialQuery)setTab('catalog');},[initialQuery]);
 const Heading=embedded?'h2':'h1';
 return <section className={'import-workspace'+(online?' is-online':'')}>
  {!hideHeading&&<div className="import-workspace-heading"><div><p className="eyebrow">{online?'Сразу к истории':'Продолжение твоей коллекции'}</p><Heading>{online?'Смотри и читай сейчас':'Найти и сохранить'}</Heading><p>{online?'Выбери произведение и источник. Откроем здесь, без сохранения в Google Диск.':'Выбери тайтл, перевод и нужные главы или серии. Остальное сделает сервер.'}</p></div></div>}
  <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="import-tabs catalog-main-tabs" aria-label="Каталог и импорт"><Tabs.Trigger value="catalog">Найти произведение</Tabs.Trigger><Tabs.Trigger value="link">По ссылке</Tabs.Trigger><Tabs.Trigger value="calendar">Календарь</Tabs.Trigger>{<Tabs.Trigger value="queue">Мои загрузки{service.active&&<i className="tab-live-dot"/>}</Tabs.Trigger>}</Tabs.List>
   <Tabs.Content value="catalog"><CatalogBrowser destination={destination} initialItem={initialItem} initialKind={initialKind} initialQuery={initialQuery} onOpenLibrary={onOpenLibrary} state={state} service={service} onSubmitted={submitted} onItems={setItems}/></Tabs.Content>
   <Tabs.Content value="calendar"><ReleaseCalendar items={items}/><ReleaseAnnouncements service={service}/></Tabs.Content>
   {<Tabs.Content value="queue"><ImportQueue service={service}/></Tabs.Content>}
   <Tabs.Content value="link"><div className="import-link-layout"><div className="import-link-intro"><span className="import-link-icon"><Icon name="cloud" size={29}/></span><p className="eyebrow">Уже знаешь, где искать?</p><h2>Начни со ссылки</h2><p>Укажи страницу произведения, главы или плеера. Сначала проверим опубликованные файлы — затем выберешь нужное.</p><ul><li>Видео · серии и разные озвучки</li><li>Манга и манхва · главы и тома</li><li>RU · EN · JA · KO</li></ul></div><div className="import-link-form"><div className="world-destinations" role="group" aria-label="Открыть или сохранить по ссылке">{[['online','Онлайн'],['drive','В Google Диск'],['local','На устройство']].map(([id,label])=><button key={id} aria-pressed={target===id} onClick={()=>setTarget(id)}>{label}</button>)}</div><ImportSelection destination={target} onOpenLibrary={onOpenLibrary} state={state} service={service} manual onSubmitted={submitted}/></div></div></Tabs.Content>
  </Tabs.Root>
 </section>;
}
