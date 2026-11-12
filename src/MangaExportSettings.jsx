import UiSelect from './UiSelect.jsx';
import './manga-export.css';
const choices={
 mode:[['original','Исходные страницы'],['translate','Перевести на ВМ · готовое из кэша'],['cached','Только готовый перевод из кэша']],
 format:[['cbz','CBZ · рекомендуется'],['zip','ZIP · изображения'],['pdf','PDF · для документов']],
 grouping:[['chapters','Отдельный файл на главу'],['volumes','Отдельный файл на том'],['single','Все выбранные главы в один файл']],
 directModel:[['gemini-3.5-flash-lite','Gemini 3.5 Flash Lite'],['gemini-3.1-flash-lite','Gemini 3.1 Flash Lite'],['gemini-2.5-flash-lite','Gemini 2.5 Flash Lite'],['gemma-4-26b-a4b-it','Gemma 4 · 26B'],['gemma-4-31b-it','Gemma 4 · 31B']],
 language:[['Japanese','Японский'],['English','Английский'],['Korean','Корейский'],['Chinese (Simplified)','Китайский']],
 directInput:[['vision','Страницы · разметка Google'],['annotated','Страницы с рамками'],['blocks','Текстовые блоки'],['coordinates','Координаты и страницы']],
 directDetector:[['en-fast','Быстрый'],['rtdetr','RT-DETR'],['ctd','Comic Text Detector'],['yolo26n-manga','YOLO Manga'],['ppocrv6-det','PaddleOCR']],
 inpaint:[['fast','Быстрая очистка'],['quality','Качественная очистка'],['moebius','Moebius'],['migan','MI-GAN']],
 font:[['auto','Автоматически'],['comic-relief','Comic Relief'],['balsamiq-sans','Balsamiq Sans'],['pangolin','Pangolin'],['neucha','Neucha'],['pt-serif','PT Serif'],['caveat','Caveat'],['ruslan-display','Ruslan Display'],['marck-script','Marck Script'],['press-start','Press Start'],['system','Системный']],
 directBatchPages:[[2,'2 страницы'],[3,'3 страницы']],direction:[['rtl','Справа налево'],['ltr','Слева направо']]
};
export default function MangaExportSettings({value,onChange,disabled=false,chapterOnly=false,hideMode=false}){
 const set=(key,next)=>onChange({...value,[key]:next});
 const field=(key,label)=> <label className="form-field input-label" key={key}>{label}<UiSelect aria-label={label} disabled={disabled} value={value[key]} onValueChange={next=>set(key,key==='directBatchPages'?Number(next):next)}>{choices[key].map(([v,label])=><option key={v} value={v}>{label}</option>)}</UiSelect></label>;
 return <div className="manga-export-settings"><div className="manga-export-grid">{!hideMode&&field('mode','Что сохранить')}{field('format','Формат файла')}{!chapterOnly&&field('grouping','Разбивка файлов')}{!chapterOnly&&<label className="form-field input-label">Тома · список или интервалы<input className="field-input" disabled={disabled} value={value.volumes} placeholder="Все · или 1-3, 5" onChange={e=>set('volumes',e.target.value)}/></label>}</div>
 {value.mode==='translate'&&<details><summary>Настройки перевода на ВМ</summary><div className="manga-export-grid">{[['directModel','Переводчик'],['language','Язык исходника'],['directInput','Подготовка запроса'],['directDetector','Детектор текста'],['directBatchPages','Страниц в запросе'],['inpaint','Очистка текста'],['font','Шрифт перевода'],['direction','Порядок чтения']].map(([key,label])=>field(key,label))}</div><p className="fine">Используются ключи Google, сохранённые на ВМ. Готовый перевод из кэша повторно не отправляется.</p></details>}
 <p className="fine">На устройство — обычный незашифрованный файл. В Google Диске файлы остаются зашифрованными.{value.format==='pdf'?' PDF сохраняет страницы в JPEG; CBZ и ZIP сохраняют качество готовых изображений.':''}</p></div>;
}
