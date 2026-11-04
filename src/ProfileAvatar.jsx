import {useRef,useState,useSyncExternalStore} from 'react';
import {Camera,X} from 'lucide-react';
const listeners=new Set();const emit=()=>listeners.forEach(fn=>fn());
const key=user=>'mv_avatar:'+encodeURIComponent(user||'anonymous');
function read(user){try{return localStorage.getItem(key(user))||'';}catch{return '';}}
export default function ProfileAvatar({user,className='',editable=false}){
 const identity=user?.sub||user?.email||'anonymous',input=useRef(null),[error,setError]=useState('');
 const source=useSyncExternalStore(fn=>{listeners.add(fn);addEventListener('storage',fn);return()=>{listeners.delete(fn);removeEventListener('storage',fn);};},()=>read(identity),()=>''),initial=(user?.given_name||user?.email||'М').slice(0,1).toUpperCase();
 function save(value){try{value?localStorage.setItem(key(identity),value):localStorage.removeItem(key(identity));emit();setError('');}catch{setError('Не удалось сохранить аватар на устройстве.');}}
 async function upload(file){if(!file)return;try{if(!/^image\/(png|jpeg|webp|gif|avif)$/.test(file.type)||file.size>12*1024*1024)throw Error('Выбери изображение PNG, JPEG, WebP или GIF до 12 МБ.');const bitmap=await createImageBitmap(file),canvas=document.createElement('canvas');canvas.width=canvas.height=256;const size=Math.min(bitmap.width,bitmap.height);canvas.getContext('2d').drawImage(bitmap,(bitmap.width-size)/2,(bitmap.height-size)/2,size,size,0,0,256,256);bitmap.close();save(canvas.toDataURL('image/webp',.85));}catch(e){setError(e.message||'Не удалось прочитать изображение.');}}
 const image=source?<img src={source} alt="Аватар профиля"/>:<span>{initial}</span>;
 return editable?<div className="profile-avatar-editor"><button className={'profile-avatar-image '+className} aria-label="Выбрать аватар профиля" title="Выбрать аватар профиля" onClick={()=>input.current?.click()}>{image}<Camera size={15}/></button><input ref={input} type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/avif" hidden onChange={e=>{upload(e.target.files?.[0]);e.target.value='';}}/>{source&&<button className="text-link" onClick={()=>save('')}><X size={12}/>Убрать</button>}<small>Сохраняется в этом браузере</small>{error&&<small role="alert">{error}</small>}</div>:<span className={'profile-avatar-image '+className}>{image}</span>;
}
