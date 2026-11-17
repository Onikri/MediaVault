import {Component} from 'react';

// A render error inside one part of the site (a reader, a player) shows its
// message in place of that part instead of blanking the whole page. A part of
// the site that failed to download after a new release reloads the page once.
export const staleChunk=error=>/dynamically imported module|Importing a module script failed|error loading dynamically|Failed to fetch dynamically|ChunkLoadError/i.test(String(error?.message||error));
const RELOADED='mediavault_stale_reload';
export function reloadForNewRelease(){
 try{const last=Number(sessionStorage.getItem(RELOADED))||0;if(Date.now()-last<30000)return false;sessionStorage.setItem(RELOADED,String(Date.now()));}catch{}
 location.reload();return true;
}

export default class CrashBoundary extends Component{
 state={error:null};
 static getDerivedStateFromError(error){return {error};}
 componentDidCatch(error,info){
  console.error('MediaVault: '+(this.props.label||'part of the page')+' failed',error,info?.componentStack);
  if(staleChunk(error))reloadForNewRelease();
 }
 render(){
  const {error}=this.state;if(!error)return this.props.children;
  const stale=staleChunk(error);
  return <div className={'inline-error crash-boundary '+(this.props.className||'')} role="alert">
   <p>{stale?'Сайт обновился — загружаем новую версию.':(this.props.label||'Эта часть страницы')+' не открылась: '+(error.message||String(error))}</p>
   <button type="button" className="text-link" onClick={()=>stale?location.reload():this.setState({error:null})}>{stale?'Перезагрузить':'Попробовать снова'}</button>
  </div>;
 }
}
