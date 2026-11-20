import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import * as Tabs from '@radix-ui/react-tabs';
import {NavigationItem,NavigationRail} from './SectionNavigation.jsx';
import {Hand,Wifi} from 'lucide-react';
import ReaderModePicker from './ReaderModePicker.jsx';
import UiSegmented from './UiSegmented.jsx';
import UiSelect from './UiSelect.jsx';
import {TITLE_UPSCALE_MODELS} from './title-upscale-model.js';
import './reader-view-settings.css';

const spring={type:'spring',stiffness:420,damping:36};

export function ReaderSettingsTabs({tabs,value,onChange,children}){
 const reduce=useReducedMotion();
 return <Tabs.Root className="reader-settings" value={value} onValueChange={onChange}>
  <NavigationRail as={Tabs.List} className="reader-settings-tabs" count={tabs.length} aria-label="Разделы настроек читалки">
   {tabs.map(([id,label])=><NavigationItem as={Tabs.Trigger} key={id} value={id} label={label}/>)}
  </NavigationRail>
  <Tabs.Content value={value} asChild>
   <motion.div key={value} className="reader-settings-pane" initial={reduce?false:{opacity:0}} animate={{opacity:1}} transition={{duration:reduce?0:.15}}>
    {children}
   </motion.div>
  </Tabs.Content>
 </Tabs.Root>;
}
function Row({label,children,wide,hint}){return <div className={'reader-view-row'+(wide?' is-wide':'')}><span>{label}{hint&&<small>{hint}</small>}</span>{children}</div>;}
export function Toggle({label,checked,onChange,children}){
 return <label className="reader-view-toggle"><span>{label}{children}</span><input type="checkbox" role="switch" checked={!!checked} onChange={e=>onChange(e.target.checked)}/></label>;
}
// section="view": how pages look. section="navigation": how pages turn and load.
export default function ReaderViewSettings({prefs,update,saveData=false,section='view',stripChapter=false,narrow=false,onShowZones,onEnableAutoScroll}){
 const reduce=useReducedMotion(),paged=prefs.mode!=='scroll';
 if(section==='navigation')return <div className="reader-layout-settings reader-view-settings">
  <section aria-label="Чтение">
   <h3>Чтение</h3>
   <Row label="Направление чтения" hint="Порядок страниц в развороте и реплик при переводе"><UiSegmented label="Направление чтения" value={prefs.direction} onChange={direction=>update({direction})} options={[['rtl','Справа налево'],['ltr','Слева направо']]}/></Row>
  </section>
  {paged?<section aria-label="Листание">
   <h3>Листание</h3>
   <Row label="Следующая страница" wide><UiSegmented className="is-wide" label="Сторона следующей страницы" value={prefs.navigationDirection} onChange={navigationDirection=>update({navigationDirection})} options={[['right','Справа','Касание справа, свайп влево'],['left','Слева','Касание слева, свайп вправо'],['reading','По чтению','Сторона зависит от направления чтения']]}/></Row>
   <p className="reader-hint">{prefs.navigationDirection==='reading'?(prefs.direction==='rtl'?'Сейчас следующая страница — касание слева, как в японской манге.':'Сейчас следующая страница — касание справа.'):prefs.navigationDirection==='left'?'Касание слева и свайп вправо открывают следующую страницу. Стрелки клавиатуры работают так же.':'Касание справа и свайп влево открывают следующую страницу. Стрелки клавиатуры работают так же.'}</p>
   <Row label="Перелистывание"><UiSegmented label="Анимация перелистывания" value={prefs.transition} onChange={transition=>update({transition})} options={[['simple','Быстрое'],['curl','3D-бумага']]}/></Row>
  </section>:<section aria-label="Прокрутка">
   <h3>Прокрутка</h3>
   <p className="reader-hint">Вебтун читается сплошной лентой. Касание у верхнего или нижнего края прокручивает на экран, по центру открывает меню.</p>
  </section>}
  <button type="button" className="reader-zones-button" onClick={onShowZones}><Hand size={16}/>Показать зоны касания</button>
  <section aria-label="Автоматическое чтение">
   <h3>Автоматическое чтение</h3>
   <Toggle label="Автопереход к следующей главе" checked={prefs.autoNext} onChange={autoNext=>update({autoNext})}>
    <small>Продолжай прокрутку после последней страницы.</small>
   </Toggle>
   <Toggle label="Автопрокрутка" checked={prefs.autoScroll} onChange={autoScroll=>{update({autoScroll});if(autoScroll)onEnableAutoScroll?.();}}/>
   {prefs.autoScroll&&<Row label="Скорость прокрутки"><UiSegmented label="Скорость прокрутки" value={prefs.autoScrollSpeed} onChange={autoScrollSpeed=>update({autoScrollSpeed})} options={[['slow','Медленно'],['normal','Обычно'],['fast','Быстро']]}/></Row>}
  </section>
  <section aria-label="Загрузка">
   <h3>Загрузка</h3>
   <Row label="Соседние страницы"><UiSegmented label="Предзагрузка страниц" value={prefs.preload} onChange={preload=>update({preload:Number(preload)})} options={[[0,'Нет'],[1,'1'],[2,'2'],[4,'4']]}/></Row>
   <Toggle label="Подготовить следующую главу" checked={prefs.nextChapter} onChange={nextChapter=>update({nextChapter})}/>
   <p className="reader-hint"><Wifi size={13}/>{saveData?'Экономия трафика устройства: предзагрузка отключена.':'Исходники и подготовленные фоны главы кэшируются зашифрованными на устройстве.'}</p>
  </section>
 </div>;
 return <div className="reader-layout-settings reader-view-settings">
  <ReaderModePicker value={prefs.mode} onChange={mode=>update({mode,...(mode==='focus'?{fit:'page'}:{})})} unavailable={stripChapter?{spread:'В этой главе полосы вебтуна: разворот недоступен'}:narrow?{spread:'Для разворота нужна читалка шире 760 пикселей'}:{}}/>
  {stripChapter?<p className="reader-hint">В главе длинные полосы вебтуна. Они показываются по одной во всю ширину, поэтому разворот выключен.</p>:narrow&&<p className="reader-hint">Разворот появится на широком экране или в полноэкранном режиме.</p>}
  <section aria-label="Страница">
   <h3>Страница</h3>
   {paged&&<Row label="Масштаб"><UiSegmented label="Масштаб страницы" value={prefs.fit} onChange={fit=>update({fit})} options={[['width','По ширине'],['page','Целиком']]}/></Row>}
   <Row label="Тема"><UiSegmented label="Тема читалки" value={prefs.theme} onChange={theme=>update({theme})} options={[['dark','Тёмная'],['black','OLED'],['paper','Бумага']]}/></Row>
   <Toggle label="Улучшать небольшие страницы" checked={prefs.upscale} onChange={upscale=>update({upscale})}><small>Нейросеть на CPU, крупные исходники не трогает</small></Toggle>
   <AnimatePresence initial={false}>{prefs.upscale&&<motion.div key="upscale" className="reader-view-reveal" initial={reduce?{opacity:0}:{opacity:0,height:0}} animate={{opacity:1,height:'auto'}} exit={reduce?{opacity:0}:{opacity:0,height:0}} transition={reduce?{duration:.1}:spring}>
    <Row label="Модель"><UiSelect aria-label="Модель улучшения манги" value={prefs.upscaleModel} onChange={e=>update({upscaleModel:e.target.value})}>{Object.values(TITLE_UPSCALE_MODELS).map(model=><option key={model.id} value={model.id}>{model.label}</option>)}</UiSelect></Row>
    <p className="reader-hint">SPAN — 1,67 МБ, цвет и штрихи. FSRCNN — 35 КБ, быстрые контуры. Модели кэшируются по проверенному хэшу.</p>
   </motion.div>}</AnimatePresence>
  </section>
 </div>;
}
