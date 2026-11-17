// A tab that stays open across a deployment still references the previous
// build's hashed files, which the new deployment no longer serves. Workers and
// lazy chunks then fail to load. Tell that case apart from a real failure.
export const entryAsset=text=>/assets\/main-[\w-]+\.js/.exec(String(text||''))?.[0]||'';
export const buildChanged=(loaded,published)=>!!entryAsset(loaded)&&!!entryAsset(published)&&entryAsset(loaded)!==entryAsset(published);
export async function staleBuild(){
 try{
  const loaded=[...document.scripts].map(script=>script.src).find(entryAsset);
  if(!loaded)return false;
  const response=await fetch(new URL('./',document.baseURI),{cache:'no-store',signal:AbortSignal.timeout(8000)});
  return response.ok&&buildChanged(loaded,await response.text());
 }catch{return false;}
}
export const STALE_BUILD_MESSAGE='Сайт обновился, пока страница была открыта. Перезагрузи страницу и повтори перевод.';
