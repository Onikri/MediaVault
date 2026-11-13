import {useEffect,useMemo,useRef,useState} from 'react';
import {clearGuestSession,readGuestSession,useGuestSession} from './guest-session.js';
import {notificationStore} from './notification-store.js';
import {profileNeedsRefresh,previewNeedsRetry} from './title-metadata.js';
import {allohaJob,allohaRequest} from './alloha-connector.js';

// The server pass walks the whole library, so it is requested only when a frame
// or dossier is actually due under the shared back-off, and at most once per
// six hours per library on this device: reloading the page must not restart it.
const ENRICH_COOLDOWN=6*3600000;
export function libraryEnrichmentDue(catalog,now=Date.now()){
  const items=(catalog?.items||[]).filter(item=>item.category==='video'||item.category==='manga');
  if(!items.length)return false;
  return items.some(item=>previewNeedsRetry(item,now))||Object.values(catalog.titleProfiles||{}).some(profile=>profileNeedsRefresh(profile,now));
}
// Library artwork passes run unattended: only a request for Drive access is news.
export const jobNoticeWanted=job=>['completed','failed','waiting_auth'].includes(job.status)&&(job.progress?.taskType!=='enrich'||job.status==='waiting_auth');
function enrichCooldownKey(libraryId){return 'mediavault_enrich_requested:'+libraryId;}
function enrichRequestedRecently(libraryId,now=Date.now()){try{return now-Number(localStorage.getItem(enrichCooldownKey(libraryId))||0)<ENRICH_COOLDOWN;}catch{return false;}}
function rememberEnrichRequest(libraryId,now=Date.now()){try{localStorage.setItem(enrichCooldownKey(libraryId),String(now));}catch{}}

export function validateServer(value){
  if(!value?.trim())return '';
  const url=new URL(value.trim());
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw Error('Нужен HTTPS-адрес твоего сервера без пути и параметров.');
  return url.origin;
}
function storedServer(){try{return validateServer(window.MEDIA_VAULT_CONFIG?.importServerUrl||localStorage.getItem('mediavault_import_server')||'');}catch{return '';}}
export function createImportClient(server,googleToken,fetcher=fetch,guestSession=()=>null){
  let session=null,signing=null;
  async function request(path,options={}){
    const {method='GET',body,auth=true,headers={},signal,raw=false,keepalive=false}=options;
    if(!server)throw Error('Сервер импорта ещё не подключён.');
    if(auth&&!session){if(keepalive)throw Error('Сессия уже закрыта.');await authenticate();}
    const binary=body instanceof Blob||body instanceof ArrayBuffer||ArrayBuffer.isView(body);
    const response=await fetcher(server+path,{method,keepalive,signal:signal||AbortSignal.timeout(['/manga/inspect','/manga/summary'].includes(path)?120000:path==='/manga/search'?45000:['/sources/discover','/sources/calendar'].includes(path)?90000:path==='/sources/search'||path.startsWith('/sources/search?')?65000:path.startsWith('/sources/')?25000:20000),headers:{...(body?{'Content-Type':binary?'application/octet-stream':'application/json'}:{}),...(auth?{Authorization:'Bearer '+session.token}:{}),...headers},...(body?{body:binary?body:JSON.stringify(body)}:{})});
    if(raw&&response.ok)return response;
    const result=await response.json().catch(()=>({}));
    if(!response.ok){
      if(response.status===401&&auth){
        session=null;
        if(!options.reauthenticated&&!keepalive){
          await authenticate();
          return request(path,{...options,reauthenticated:true});
        }
      }
      throw Object.assign(Error(typeof result.detail==='string'?result.detail:'Сервер не выполнил запрос.'),{status:response.status});
    }
    return result;
  }
  async function authenticate(){
    if(signing)return signing;
    signing=(async()=>{
      const health=await request('/health',{auth:false});
      if(health.application!=='MediaVault'||health.version<4||health.origin!==window.location.origin)throw Error('Этот адрес не подтвердил конфигурацию MediaVault.');
      const token=await googleToken();
      const guest=!token&&guestSession();
      if(guest){
        // Guest profile: the owner-issued session token is the server session.
        const response=await fetcher(server+'/guests/me',{signal:AbortSignal.timeout(20000),headers:{Authorization:'Bearer '+guest.token}});
        const data=await response.json().catch(()=>({}));
        if(!response.ok){if(response.status===401||response.status===403)clearGuestSession();throw Error(typeof data.detail==='string'?data.detail:'Сервер не подтвердил гостевой вход.');}
        session={token:guest.token,guest:data.guest,role:'guest',driveConnected:false,serverVersion:health.version};return session;
      }
      if(!token)throw Error('Сначала войди через Google.');
      const response=await fetcher(server+'/auth/session',{method:'POST',signal:AbortSignal.timeout(20000),headers:{Authorization:'Bearer '+token}});
      const data=await response.json();if(!response.ok)throw Error(data.detail||'Сервер не подтвердил вход.');
      session={...data,serverVersion:health.version,googleGatewayVersion:health.googleGatewayVersion||0,ranobeDriveAudio:health.ranobeDriveAudio===true,mangaDriveTranslation:health.mangaDriveTranslation===true};return session;
    })();
    try{return await signing;}finally{signing=null;}
  }
  return {request,authenticate,patchSession:change=>{if(session)session={...session,...change};return session;},reset:()=>{session=null;},getSession:()=>session};
}

export function useImportService(state,actions){
  const [server,setAddress]=useState(storedServer),[status,setStatus]=useState('idle'),[error,setError]=useState(''),[session,setSession]=useState(null),[jobs,setJobs]=useState([]);
  const live=useRef(state);live.current=state;
  const guest=useGuestSession(),guestToken=!state.user?guest?.token||'':'';
  const client=useMemo(()=>createImportClient(server,()=>live.current.user?actions.ensureSession():null,fetch,()=>guestToken?readGuestSession():null),[server,state.user?.sub,guestToken]);
  const refreshSignature=useRef('');
  const enrichmentRequested=useRef('');
  const previousJobs=useRef(new Map());
  const active=jobs.some(job=>['queued','running','cancelling'].includes(job.status));
  function setServer(value){const address=validateServer(value);try{localStorage.setItem('mediavault_import_server',address);}catch{}setAddress(address);}
  useEffect(()=>{
    let closed=false,timer,checking=false,nextSessionCheck=0;
    setSession(null);setJobs([]);setError('');refreshSignature.current='';previousJobs.current.clear();
    const noticeKey='mv_job_states_v1:'+state.user?.sub+':'+server;let lastPoll=0;
    try{const saved=JSON.parse(localStorage.getItem(noticeKey)||'{}');previousJobs.current=new Map(saved.states||[]);lastPoll=Number(saved.at)||0;}catch{}
    if(server&&!state.user&&guestToken){
      // Guests only watch: keep the session verified, never poll owner jobs.
      const check=async()=>{if(closed)return;try{setStatus(previous=>previous==='connected'?'connected':'connecting');const access=await client.authenticate();if(!closed){setSession(access);setStatus('connected');setError('');}}catch(cause){if(!closed){setStatus('error');setError(cause.message);}}if(!closed)timer=setTimeout(()=>{client.reset();check();},300000);};
      check();return()=>{closed=true;clearTimeout(timer);client.reset();};
    }
    if(!server||!state.admin||!state.user||!state.token){setStatus(server?'disconnected':'unconfigured');return;}
    async function update(force=false){
      if(checking||closed)return;checking=true;clearTimeout(timer);
      try{
        setStatus(previous=>previous==='connected'?'connected':'connecting');
        const cached=client.getSession();
        const access=(!cached||force||(!cached.driveConnected&&Date.now()>nextSessionCheck))?await client.authenticate():cached;
        nextSessionCheck=Date.now()+30000;
        const response=await client.request('/jobs');
        if(!closed){
          const notices=notificationStore(state.user?.sub);
          for(const job of response.jobs||[]){const prior=previousJobs.current.get(job.id);if((prior?prior!==job.status:lastPoll>0&&job.updated*1000>lastPoll)&&jobNoticeWanted(job))notices.push({id:'job:'+job.id+':'+job.status+':'+job.updated,taskId:job.id,bad:job.status!=='completed',message:(job.progress?.title||'Задание')+' · '+({completed:'готово',failed:'нужно продолжить',waiting_auth:'нужен фоновый доступ Drive'}[job.status])});}
          previousJobs.current=new Map((response.jobs||[]).map(j=>[j.id,j.status]));
          lastPoll=Date.now();try{localStorage.setItem(noticeKey,JSON.stringify({states:[...previousJobs.current],at:lastPoll}));}catch{}
        }
        const connection=response.driveConnection,nextAccess=connection?client.patchSession({driveConnected:connection.connected,driveNeedsConsent:connection.needsConsent}):access;
        if(!closed){setSession(nextAccess);setJobs(response.jobs||[]);setStatus('connected');setError('');}
      }catch(cause){if(!closed){setStatus('error');setError(cause.message);}}
      checking=false;if(!closed)timer=setTimeout(update,4500);
    }
    const focus=()=>update(true);window.addEventListener('focus',focus);
    update();return()=>{closed=true;clearTimeout(timer);window.removeEventListener('focus',focus);client.reset();};
  },[server,state.admin,state.user?.sub,!!state.token,client,guestToken]);
  useEffect(()=>{
    if(!state.catalog||state.busy||!state.driveConnected)return;
    const signature=jobs.map(j=>j.id+':'+(j.progress?.saved||0)+':'+(j.status==='completed'?'done':'')).join('|');
    if(!signature||signature===refreshSignature.current)return;
    if(jobs.some(j=>j.progress?.saved>0||j.status==='completed')){
      refreshSignature.current=signature;
      actions.refreshCatalog({silent:true}).then(ok=>{if(!ok&&refreshSignature.current===signature)refreshSignature.current='';});
    }
  },[jobs,state.catalog?.folderId,!!state.busy,state.driveConnected]);
  async function refresh(){const result=await client.authenticate();setSession(result);if(result.role==='guest'){setStatus('connected');return result;}const data=await client.request('/jobs');setJobs(data.jobs);setStatus('connected');return result;}
  async function configureGoogle(configuration){
    await client.request('/admin/google-oauth',{method:'POST',body:configuration});
    return refresh();
  }
  async function connect(){
    const popup=window.open('about:blank','mediavault-drive-consent','popup,width=560,height=720');
    if(!popup)throw Error('Разреши всплывающее окно для подключения Google Drive.');
    try{
      const data=await client.request('/oauth/start',{method:'POST'});
      if(new URL(data.url).origin!=='https://accounts.google.com')throw Error('Некорректный адрес Google.');
      popup.location=data.url;
      await new Promise((resolve,reject)=>{
        const finish=(error)=>{window.removeEventListener('message',message);clearInterval(timer);clearTimeout(timeout);error?reject(error):resolve();};
        const message=event=>{if(event.origin===server&&event.source===popup&&event.data?.type==='mediavault-server-connected')finish();};
        window.addEventListener('message',message);
        const timer=setInterval(()=>{if(popup.closed)finish();},1000),timeout=setTimeout(()=>finish(Error('Время подключения истекло. Повтори вход.')),180000);
      });
      const result=await refresh();if(!result.driveConnected)throw Error('Google Drive ещё не подключён к серверу.');
    }catch(cause){popup.close();throw cause;}
  }
  async function submit(job){
    if(!session?.driveConnected)throw Error('Подключи Google Drive к серверу перед первым импортом.');
    const task=await client.request('/jobs',{method:'POST',body:{job:allohaJob(job,session.serverVersion),vault_key:actions.getServerKey()},headers:{'Idempotency-Key':crypto.randomUUID()}});
    setJobs(old=>[task,...old.filter(value=>value.id!==task.id)]);return task;
  }
  async function enrichLibrary(titleId){
    if(!session?.driveConnected)throw Error('Подключи фоновый доступ сервера к Drive.');
    const raw=state.libraryId+':'+(titleId||'all')+':'+Date.now();
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));
    const id='enrich-'+[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
    const task=await client.request('/library/enrich',{method:'POST',body:{library_id:state.libraryId,vault_key:actions.getServerKey(),...(titleId?{title_id:titleId}:{})},headers:{'Idempotency-Key':id}});
    setJobs(old=>[task,...old.filter(value=>value.id!==task.id)]);return task;
  }
  useEffect(()=>{
    const key=state.user?.sub+':'+state.libraryId;
    if(!state.catalog||!state.admin||state.busy||!session?.driveConnected||!(session.serverVersion>=5)||enrichmentRequested.current===key)return;
    enrichmentRequested.current=key;
    const pending=jobs.some(job=>job.progress?.taskType==='enrich'&&['queued','running'].includes(job.status));
    if(pending||enrichRequestedRecently(state.libraryId)||!libraryEnrichmentDue(state.catalog))return;
    rememberEnrichRequest(state.libraryId);
    enrichLibrary().catch(()=>{enrichmentRequested.current='';try{localStorage.removeItem(enrichCooldownKey(state.libraryId));}catch{}});
  },[state.catalog,!!state.busy,session?.driveConnected,session?.serverVersion]);
  async function operation(id,op){const task=await client.request('/jobs/'+encodeURIComponent(id)+'/'+op,{method:'POST'});setJobs(old=>old.map(value=>value.id===id?task:value));return task;}
  const request=useMemo(()=>(path,options)=>client.request(path,allohaRequest(path,options,session?.serverVersion)),[client,session?.serverVersion]);
  return {server,setServer,status,error,session,jobs,active,connect,submit,refresh,configureGoogle,enrichLibrary,
    openReaderChapter:(item,names,direction,signal,model)=>client.request('/api/v1/chapters',{method:'POST',body:{library_id:live.current.libraryId,item_id:item.id,vault_key:actions.getServerKey(),names,direction,...(model?{model}:{})},signal}),
    request,cancel:id=>operation(id,'cancel'),resume:id=>operation(id,'resume')};
}
