import React,{useEffect,useState} from 'react';
import LibraryCalendar from './LibraryCalendar.jsx';
import {Search,Link,CalendarDays,Download,HardDriveUpload} from 'lucide-react';
import LocalTitleUpload from './LocalTitleUpload.jsx';
import * as Tabs from '@radix-ui/react-tabs';
import Icon from './Icons.jsx';
import ReleaseAnnouncements from './ReleaseAnnouncements.jsx';
import CatalogBrowser from './CatalogBrowser.jsx';
import ImportSelection from './ImportSelection.jsx';
import {ImportSettings,ImportQueue,ReleaseCalendar} from './ImportParts.jsx';
import './import-workspace.css';
export default function ServerImport({state,actions,service,onConnect,onOpenLibrary,initialItem,initialQuery,initialFilters,initialKind,destination='drive',initialTab='catalog',embedded=false,hideHeading=false,favoritesOnly=false,head}){
 const [target,setTarget]=useState(destination),[tab,setTab]=useState(initialTab),[items,setItems]=useState([]),online=destination==='online';
 const submitted=()=>setTab('queue');
 useEffect(()=>{if(initialQuery)setTab('catalog');},[initialQuery]);
 const Heading=embedded?'h2':'h1';
 return <section className={'import-workspace'+(online?' is-online':'')}>
  {!hideHeading&&<div className="import-workspace-heading"><div><p className="eyebrow">{online?'Сразу к истории':'Продолжение твоей коллекции'}</p><Heading>{online?'Смотри и читай сейчас':'Найти и сохранить'}</Heading><p>{online?'Выбери произведение и источник. Откроем здесь, без сохранения в Google Диск.':'Выбери тайтл, перевод и нужные главы или серии. Остальное сделает сервер.'}</p></div></div>}
  <Tabs.Root value={tab} onValueChange={setTab}>{(()=>{const list=<Tabs.List className={'import-tabs catalog-main-tabs catalog-action-bar'+(head?' is-compact':'')} aria-label="Каталог и импорт"><Tabs.Trigger value="catalog" title="Найти произведение"><Search size={15}/><span className="tab-label">Найти произведение</span></Tabs.Trigger><Tabs.Trigger value="link" title="По ссылке"><Link size={15}/><span className="tab-label">По ссылке</span></Tabs.Trigger>{actions&&<Tabs.Trigger value="local" title="С компьютера"><HardDriveUpload size={15}/><span className="tab-label">С компьютера</span></Tabs.Trigger>}<Tabs.Trigger value="calendar" title="Календарь"><CalendarDays size={15}/><span className="tab-label">Календарь</span></Tabs.Trigger>{!embedded&&<Tabs.Trigger value="queue" title="Загрузки"><Download size={15}/><span className="tab-label">Загрузки</span>{service.active&&<i className="tab-live-dot"/>}</Tabs.Trigger>}</Tabs.List>;return head?<div className="catalog-head">{head}{list}</div>:list;})()}
   <Tabs.Content value="catalog"><CatalogBrowser favoritesOnly={favoritesOnly} destination={destination} initialItem={initialItem} initialKind={initialKind} initialQuery={initialQuery} initialFilters={initialFilters} onOpenLibrary={onOpenLibrary} state={state} service={service} onSubmitted={submitted} onItems={setItems}/></Tabs.Content>
   {actions&&<Tabs.Content value="local"><div className="import-link-layout"><div className="import-link-intro"><p className="eyebrow">Своё произведение</p><h2>Добавить с компьютера</h2><p>Книга, ранобэ, манга или видео из твоих файлов. Файлы шифруются и сохраняются в твою коллекцию на Google Диске, а карточка каталога даёт тайтлу обложку, описание и онлайн-источники.</p></div><LocalTitleUpload state={state} actions={actions} service={service} onOpenLibrary={onOpenLibrary} initialKind={['book','ranobe','manga','anime','movie','tv','music'].includes(initialKind)?initialKind:'book'}/></div></Tabs.Content>}
   <Tabs.Content value="calendar"><LibraryCalendar userId={state.user?.sub}/><ReleaseAnnouncements service={service}/></Tabs.Content>
   {<Tabs.Content value="queue"><ImportQueue service={service}/></Tabs.Content>}
   <Tabs.Content value="link"><div className="import-link-layout"><div className="import-link-intro"><span className="import-link-icon"><Icon name="cloud" size={29}/></span><p className="eyebrow">Уже знаешь, где искать?</p><h2>Начни со ссылки</h2><p>Укажи страницу произведения, главы или плеера. Сначала проверим опубликованные файлы — затем выберешь нужное.</p><ul><li>Видео · серии и разные озвучки</li><li>Манга и манхва · главы и тома</li><li>RU · EN · JA · KO</li></ul></div><div className="import-link-form"><div className="world-destinations" role="group" aria-label="Открыть или сохранить по ссылке">{[['online','Онлайн'],['drive','В Google Диск'],['local','На устройство']].map(([id,label])=><button key={id} aria-pressed={target===id} onClick={()=>setTarget(id)}>{label}</button>)}</div><ImportSelection destination={target} onOpenLibrary={onOpenLibrary} state={state} service={service} manual onSubmitted={submitted}/></div></div></Tabs.Content>
  </Tabs.Root>
 </section>;
}
