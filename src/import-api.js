export function importServerUrl(){
  const value=globalThis.window?.MEDIA_VAULT_CONFIG?.importServerUrl;
  if(!value)return '';
  const url=new URL(value);
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)throw Error('Сервер импорта должен иметь HTTPS-адрес без паролей и параметров.');
  return url.href.replace(/\/$/,'');
}
export async function importRequest(token,path,{body,method='GET',signal}={}){
  const base=importServerUrl();
  if(!base)throw Error('Сервер автоматического импорта ещё не настроен.');
  if(!token)throw Error('Подключи Google заново.');
  const response=await fetch(base+path,{method,signal,credentials:'omit',cache:'no-store',
    headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},
    ...(body?{body:JSON.stringify(body)}:{})});
  const result=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(result.error||'Сервер импорта временно недоступен.');
  return result;
}
