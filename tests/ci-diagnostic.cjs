// Public CI annotations contain only fixed scenario names and code locations.
module.exports=function(error,file,scenario){
  const name=['TimeoutError','AssertionError','TypeError','ReferenceError'].includes(error?.name)?error.name:'Error';
  const frame=String(error?.stack||'').match(/tests\/([a-zA-Z0-9_-]+\.(?:cjs|mjs|js)):([0-9]+)/);
  const location=frame?'file=tests/'+frame[1]+',line='+frame[2]:'file='+file;
  const api=String(error?.message||'').match(/^(?:page|locator|browser|browserContext)\.[a-zA-Z]+/)?.[0];
  console.error('::error '+location+'::'+scenario+' failed: '+name+(api?' ('+api+')':''));
};
