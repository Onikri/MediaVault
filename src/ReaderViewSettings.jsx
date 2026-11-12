import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Wifi} from 'lucide-react';
import ReaderModePicker from './ReaderModePicker.jsx';
import UiSegmented from './UiSegmented.jsx';
import UiSelect from './UiSelect.jsx';
import {TITLE_UPSCALE_MODELS} from './title-upscale-model.js';
import './reader-view-settings.css';

const spring={type:'spring',stiffness:420,damping:36};
// Tabs whose selection pill morphs; the panel content slides in the direction of travel.
export function ReaderSettingsTabs({tabs,value,onChange,children}){
 const reduce=useReducedMotion(),index=tabs.findIndex(([id])=>id===value);
 return <div className="reader-settings">
  <div className="reader-settings-tabs" role="tablist" aria-label="Разделы настроек читалки">
   {tabs.map(([id,label])=><button key={id} role="tab" aria-selected={id===value} onClick={()=>onChange(id)}>{id===value&&<motion.span layoutId="reader-settings-tab" className="reader-settings-tab-pill" transition={reduce?{duration:0}:spring}/>}<span>{label}</span></button>)}
  </div>
  <AnimatePresence mode="wait" initial={false} custom={index}>
   <motion.div key={value} className="reader-settings-pane" custom={index} initial={reduce?{opacity:0}:{opacity:0,x:index?18:-18}} animate={{opacity:1,x:0}} exit={reduce?{opacity:0}:{opacity:0,x:index?-12:12,transition:{duration:.12}}} transition={reduce?{duration:.1}:spring}>{children}</motion.div>
  </AnimatePresence>
 </div>;
}
function Row({label,children,wide}){return <div className={'reader-view-row'+(wide?' is-wide':'')}><span>{label}</span>{children}</div>;}
function Toggle({label,checked,onChange,children}){
 return <label className="reader-view-toggle"><span>{label}{children}</span><input type="checkbox" role="switch" checked={!!checked} onChange={e=>onChange(e.target.checked)}/></label>;
}
export default function ReaderViewSettings({prefs,update,saveData=false}){
 const reduce=useReducedMotion();
 return <div className="reader-layout-settings reader-view-settings">
  <ReaderModePicker value={prefs.mode} onChange={mode=>update({mode,...(mode==='focus'?{fit:'page'}:{})})}/>
  <section aria-label="Чтение">
   <h3>Чтение</h3>
   <Row label="Масштаб"><UiSegmented label="Масштаб страницы" value={prefs.fit} onChange={fit=>update({fit})} options={[['width','По ширине'],['page','Целиком']]}/></Row>
   <Row label="Порядок разворота"><UiSegmented label="Направление чтения" value={prefs.direction} onChange={direction=>update({direction})} options={[['rtl','Справа налево'],['ltr','Слева направо']]}/></Row>
   <Row label="Листать вперёд" wide><UiSegmented className="is-wide" label="Направление перелистывания" value={prefs.navigationDirection} onChange={navigationDirection=>update({navigationDirection})} options={[['right','Вправо','Кнопка вправо · свайп влево'],['left','Влево','Кнопка влево · свайп вправо'],['reading','По чтению','По направлению чтения']]}/></Row>
   <Row label="Перелистывание"><UiSegmented label="Анимация перелистывания" value={prefs.transition} onChange={transition=>update({transition})} options={[['simple','Быстрое'],['curl','3D-бумага']]}/></Row>
  </section>
  <section aria-label="Вид">
   <h3>Вид</h3>
   <Row label="Тема"><UiSegmented label="Тема читалки" value={prefs.theme} onChange={theme=>update({theme})} options={[['dark','Тёмная'],['black','OLED'],['paper','Бумага']]}/></Row>
   <Toggle label="Улучшать небольшие страницы" checked={prefs.upscale} onChange={upscale=>update({upscale})}><small>Нейросеть на CPU, крупные исходники не трогает</small></Toggle>
   <AnimatePresence initial={false}>{prefs.upscale&&<motion.div key="upscale" className="reader-view-reveal" initial={reduce?{opacity:0}:{opacity:0,height:0}} animate={{opacity:1,height:'auto'}} exit={reduce?{opacity:0}:{opacity:0,height:0}} transition={reduce?{duration:.1}:spring}>
    <Row label="Модель"><UiSelect aria-label="Модель улучшения манги" value={prefs.upscaleModel} onChange={e=>update({upscaleModel:e.target.value})}>{Object.values(TITLE_UPSCALE_MODELS).map(model=><option key={model.id} value={model.id}>{model.label}</option>)}</UiSelect></Row>
    <p className="reader-hint">SPAN — 1,67 МБ, цвет и штрихи. FSRCNN — 35 КБ, быстрые контуры. Модели кэшируются по проверенному хэшу.</p>
   </motion.div>}</AnimatePresence>
  </section>
  <section aria-label="Загрузка">
   <h3>Загрузка</h3>
   <Row label="Соседние страницы"><UiSegmented label="Предзагрузка страниц" value={prefs.preload} onChange={preload=>update({preload:Number(preload)})} options={[[0,'Нет'],[1,'1'],[2,'2'],[4,'4']]}/></Row>
   <Toggle label="Подготовить следующую главу" checked={prefs.nextChapter} onChange={nextChapter=>update({nextChapter})}/>
   <p className="reader-hint"><Wifi size={13}/>{saveData?'Экономия трафика устройства: предзагрузка отключена.':'Исходники и подготовленные фоны главы кэшируются зашифрованными на устройстве.'}</p>
  </section>
  <section aria-label="Служебное">
   <Toggle label="Показывать служебную диагностику" checked={prefs.diagnostics} onChange={diagnostics=>update({diagnostics})}/>
  </section>
 </div>;
}
