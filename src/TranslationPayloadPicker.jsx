import {Images,PanelsTopLeft} from 'lucide-react';
const descriptions={
 annotated:'Страницы с рамками и номерами. Две или три соседние страницы в одном запросе.',
 blocks:'Вырезки текста с номерами на читаемых листах. Исходные координаты и вёрстка сохраняются.',
 coordinates:'Чистые страницы и координаты детектора в одном запросе.',
 vision:'Google получает страницы и самостоятельно возвращает текстовые области.',
};
export default function TranslationPayloadPicker({value,onChange}){
 return <div className="reader-payload-picker"><h4>Что отправлять Google</h4><div role="group" aria-label="Формат отправки перевода">
 <button type="button" aria-label="Страницы с рамками" title={descriptions.annotated} aria-pressed={value!=='blocks'} onClick={()=>onChange('annotated')}><Images size={22}/></button>
 <button type="button" aria-label="Блоки на листе" title={descriptions.blocks} aria-pressed={value==='blocks'} onClick={()=>onChange('blocks')}><PanelsTopLeft size={22}/></button>
 <span>{value==='blocks'?'Блоки на листе':'Страницы'}</span>
 </div><p className="reader-payload-description" role="status">{descriptions[value]||descriptions.annotated}</p></div>;
}
