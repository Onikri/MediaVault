import {useEffect,useState} from 'react';
import {ShieldCheck,Fingerprint,Check,X} from 'lucide-react';
import {privacyPreferences,savePrivacyPreferences} from './privacy.js';
import {forgetGoogleSession} from './device-auth.js';
import {deviceStore} from './device-storage.js';
import './privacy.css';

export function CookieNotice({state,actions}){
  const [choice,setChoice]=useState(privacyPreferences);
  useEffect(()=>{const update=event=>setChoice(event.detail);window.addEventListener('mediavault-privacy',update);return()=>window.removeEventListener('mediavault-privacy',update);},[]);
  if(choice.chosen)return null;
  function accept(remember){savePrivacyPreferences(remember);if(remember&&state.user)actions.rememberAccount();}
  return <aside className="cookie-notice" role="region" aria-label="Cookies и запоминание устройства"><ShieldCheck size={21}/><div><h2>Вход запоминается на этом устройстве</h2><p>После входа через Google браузер помнит тебя 90 дней: перезагрузка страницы не выкидывает из аккаунта. Необходимые cookies хранят только настройки, без токенов и секретной фразы. Рекламы и аналитики нет. На чужом устройстве выбери «Только необходимые».</p><div><button className="btn btn-primary btn-small" onClick={()=>accept(true)}>Принять и запомнить</button><button className="text-link" onClick={()=>accept(false)}>Только необходимые</button></div></div></aside>;
}
export default function DeviceSettings({state,actions}){
  const [available,setAvailable]=useState(false),[message,setMessage]=useState('');
  useEffect(()=>{actions.biometricAvailable().then(setAvailable);},[]);
  async function forget(){await forgetGoogleSession().catch(()=>{});await deviceStore('clear');window.dispatchEvent(new Event('mediavault-forgot-device'));savePrivacyPreferences(false);setMessage('Сохранённый вход и API-ключи удалены. Текущая открытая библиотека останется доступна до выхода.');}
  return <section className="settings-card device-settings"><div className="section-heading"><h2 className="section-title"><ShieldCheck size={20}/>Вход на этом устройстве</h2></div>
    <p>На личном телефоне или планшете можно восстанавливать вход и открывать библиотеку без повторного ввода фразы. Google может потребовать повторное разрешение, если доступ отозван или истёк.</p>
    <div className="device-status">{state.restoring?'Восстанавливаем вход…':state.remembered?<><Check size={15}/>Вход сохранён на 90 дней</>:state.remembering?'Запоминание разрешено; заверши настройку после входа.':'Автоматический вход выключен'}</div>
    <div className="form-actions"><button className="btn btn-secondary btn-small" disabled={!state.user||!!state.busy} onClick={actions.rememberAccount}>{state.remembered?'Обновить сохранённый вход':'Запомнить это устройство'}</button>{state.remembering&&<button className="text-link" onClick={forget}>Забыть устройство</button>}</div>
    <div className="device-biometry"><Fingerprint size={24}/><div><strong>{state.biometric?'Разблокировка устройством включена':'Отпечаток, лицо или PIN устройства'}</strong><p>{available?'Браузер предложит доступный способ. Для шифрования нужен защищённый ключ WebAuthn PRF.':'Этот браузер не предоставил защищённую проверку устройства. Секретная фраза продолжит работать.'}</p><button className="text-link" disabled={!available||!state.catalog||!!state.busy} onClick={actions.enableBiometric}>Настроить защищённое открытие</button></div></div>
    {state.storageKept===false&&<p className="device-help">Браузер не закрепил хранилище сайта: при нехватке места на диске он может стереть сохранённый вход. Освободи место на системном диске или добавь сайт в закладки.</p>}
    {state.biometric&&!state.catalog&&state.user&&<button className="btn btn-primary" disabled={!!state.busy} onClick={actions.biometricUnlock}><Fingerprint size={18}/>Открыть библиотеку</button>}
    {(state.deviceError||message)&&<p className="device-help" role="status">{message||state.deviceError}</p>}
    <small>На общем устройстве выбирай «Только необходимые». Выход из аккаунта удаляет сохранённый вход и ключ быстрого открытия. Секретную фразу сохрани отдельно.</small>
  </section>;
}
