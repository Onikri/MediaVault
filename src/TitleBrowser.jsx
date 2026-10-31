import {AnimeGrid} from './blossom/components/AnimeGrid.tsx';
import {useMemo,useState} from 'react';
import {LayoutGrid,Grid2X2,List,Table2} from 'lucide-react';
import {buildTitles} from './library-model.js';
import TitlePage,{TitleImage} from './TitlePage.jsx';

export default function TitleBrowser({catalog,items,sort,renderFile,renderTitle,state,actions,selected,onSelectTitle,onPlay,onRelated,onImport,selectedVideo,onClosePlayer,onMetadataLoaded}){
  const [mode,setMode]=useState(()=>{try{return localStorage.getItem('mediavault_library_view')||'titles';}catch{return 'titles';}});
  const [layout,setLayout]=useState(()=>{try{const value=localStorage.getItem('mediavault_library_layout');return ['grid','compact','list','table'].includes(value)?value:'grid';}catch{return 'grid';}});
  const titles=useMemo(()=>buildTitles(catalog,items).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'ru'):(new Date(b.addedAt)-new Date(a.addedAt))),[catalog,items,sort]);
  const current=selected&&(buildTitles(catalog).find(t=>t.id===selected.id)||selected);
  function changeMode(value){setMode(value);onSelectTitle(null);try{localStorage.setItem('mediavault_library_view',value);}catch{}}
  function changeLayout(value){setLayout(value);try{localStorage.setItem('mediavault_library_layout',value);}catch{}}
  if(current)return <TitlePage key={current.id} title={current} state={state} actions={actions} onBack={()=>{onClosePlayer();onSelectTitle(null);}} onPlay={onPlay} onRelated={onRelated} onImport={onImport} selected={selectedVideo} onClosePlayer={onClosePlayer} onMetadataLoaded={onMetadataLoaded}/>;
  return <>
    <div className="title-browser-toolbar"><div className="import-tabs" role="group" aria-label="Содержимое библиотеки"><button id="showTitlesBtn" data-state={mode==='titles'?'active':'inactive'} aria-pressed={mode==='titles'} onClick={()=>changeMode('titles')}>Тайтлы</button><button id="showFilesBtn" data-state={mode==='files'?'active':'inactive'} aria-pressed={mode==='files'} onClick={()=>changeMode('files')}>Файлы</button></div><div className="library-layouts" role="group" aria-label="Вид библиотеки">{[['grid','Плитки',LayoutGrid],['compact','Маленькие плитки',Grid2X2],['list','Список',List],['table','Таблица',Table2]].map(([id,label,Icon])=><button key={id} onClick={()=>changeLayout(id)} aria-label={label} title={label} aria-pressed={layout===id}><Icon size={17}/></button>)}</div><span className="fine library-count">{titles.length} тайтлов · {items.length} файлов</span></div>
    {layout==='table'?<div className="library-table-scroll"><table className="library-table"><thead><tr><th>Название</th><th>Тип</th><th>Год</th><th>{mode==='titles'?'В коллекции':'Размер'}</th><th>Оценка</th></tr></thead><tbody>{(mode==='titles'?titles:items).map(value=>{const profile=value.profile||catalog?.titleProfiles?.[titles.find(t=>t.items.some(i=>i.id===value.id))?.id];return <tr key={value.id}><td><button onClick={()=>mode==='titles'?onSelectTitle(value):onPlay(value)}><TitleImage url={profile?.cover} profile={profile} actions={actions} libraryId={state.libraryId}/><strong>{profile?.title||value.name}</strong></button></td><td>{profile?.format||({anime:'Аниме',manga:'Манга',video:'Видео',audio:'Музыка',book:'Книга'}[value.section||value.category]||'Материал')}</td><td>{profile?.year||'—'}</td><td>{mode==='titles'?value.items.length+' файлов':Math.ceil(value.size/1024/1024)+' МБ'}</td><td>{profile?.score||'—'}</td></tr>;})}</tbody></table></div>:<AnimeGrid id="libraryGrid" className={'media-grid library-layout-'+layout}>{mode==='files'?items.map(renderFile):titles.map(title=>renderTitle(title,()=>onSelectTitle(title)))}</AnimeGrid>}
  </>;
}
