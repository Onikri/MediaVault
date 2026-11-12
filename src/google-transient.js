// Overload, quota, network and malformed answers pass with time or another key;
// a rejected key, a missing model or bad parameters do not.
export function transientGoogleError(error){
 if(!error||error.name==='AbortError'||error.refusal)return false;
 const status=Number(error.status||error.diagnostics?.httpStatus||/HTTP (\d{3})/.exec(error.message||'')?.[1])||0;
 if(status>=400)return status===408||status===429||status>=500;
 return !/ключ|Oracle|не поддерживает|лимит inline|Слишком много реплик/i.test(error.message||'');
}
export function retryAfterSeconds(error){const value=Number(error?.retryAfter||error?.diagnostics?.retryAfter||/повтор через (\d+)/.exec(error?.message||'')?.[1]);return Number.isFinite(value)&&value>0?Math.min(600,value):0;}
// Settings, not Google, are wrong: every page would fail the same way.
export function setupGoogleError(error){
 const status=Number(error?.status||/HTTP (\d{3})/.exec(error?.message||'')?.[1])||0;
 return status===401||status===403||status===404||/ключ|Oracle/i.test(error?.message||'')&&!/квот/i.test(error?.message||'');
}
