import React,{useState} from 'react';
export default function VoicePicker({discovery,onChoose,selected}){
  const [groupId,setGroupId]=useState('');
  const voices=(discovery.data?.voices||[]).filter(v=>v.language!=='en'||v.kind==='original'),group=voices.find(g=>g.id===groupId);
  return <section className="voice-picker" aria-label="Переводы со всех источников">
    <h4>Озвучка и субтитры</h4>
    {discovery.loading&&<p role="status"><span className="loading-ring"/>Проверяем точный тайтл и собираем переводы…</p>}
    {discovery.error&&<p role="alert">{discovery.error}<button type="button" className="text-link" onClick={discovery.retry}>Повторить поиск</button></p>}
    {!discovery.loading&&discovery.data&&!voices.length&&<p className="fine">Подтверждённых переводов для этого тайтла и сезона пока нет. Другие произведения не подставляются.</p>}
    {discovery.data?.complete===false&&<p className="fine">Часть источников не удалось проверить полностью. Найденные варианты сохранены; полный список пока не подтверждён. <button type="button" className="text-link" onClick={discovery.retry}>Продолжить проверку</button></p>}
    {!!voices.length&&<><label className="input-label" htmlFor="voiceGroup">Перевод · {voices.length} вариантов</label><select id="voiceGroup" className="field-input" value={groupId} onChange={e=>{setGroupId(e.target.value);const group=voices.find(v=>v.id===e.target.value);onChoose(group?.variants?.[0]||null);}}><option value="">Выбери студию или субтитры</option>{voices.map(voice=><option key={voice.id} value={voice.id}>{voice.name} · {voice.kind==='subtitles'?'субтитры':'озвучка'} · {voice.variants.length} источн.</option>)}</select></>}
    {group&&<details className="voice-source-details"><summary>Другой источник · {selected?.providerName||group.variants[0]?.providerName}</summary><label className="input-label" htmlFor="voiceSource">Доступный плеер</label><select id="voiceSource" className="field-input" value={selected?.id||''} onChange={e=>onChoose(group.variants.find(v=>v.id===e.target.value)||null)}><option value="">Выбери вариант</option>{group.variants.map(v=><option key={v.id} value={v.id}>{v.player} · {v.providerName} · {v.sourceTitle}{v.episodes.length?' · '+v.episodes.length+' сер.':''}</option>)}</select><p className="fine">Названия студий объединены; каждый плеер сохраняет свой список серий. Наличие перевода у конкретной серии перепроверяется перед просмотром.</p></details>}
    {discovery.data?.providers&&<details className="provider-diagnostics"><summary>Проверено источников: {discovery.data.providers.length}</summary>{discovery.data.providers.map(p=><p key={p.provider}><b>{p.name}</b> — {p.status==='ok'?'найдены варианты':p.status==='no_match'?'точного совпадения нет':p.message||'недоступен'}</p>)}</details>}
  </section>;
}
