// Formatting helpers for the guest activity admin.
export function bytes(n){
 const value=Number(n)||0;
 if(value<1024)return value+' Б';
 const units=['КБ','МБ','ГБ','ТБ'];let size=value/1024,unit=0;
 while(size>=1024&&unit<units.length-1){size/=1024;unit++;}
 return (size>=100?Math.round(size):size.toFixed(size>=10?1:2).replace(/\.?0+$/,''))+' '+units[unit];
}
export function ago(seconds,now=Date.now()/1000){
 if(!seconds)return 'никогда';
 const d=Math.max(0,now-seconds);
 if(d<60)return 'только что';
 if(d<3600)return Math.floor(d/60)+' мин назад';
 if(d<86400)return Math.floor(d/3600)+' ч назад';
 if(d<86400*7)return Math.floor(d/86400)+' дн назад';
 return stamp(seconds,false);
}
export function duration(seconds){
 const d=Math.max(0,Math.round(seconds));
 if(d<60)return 'меньше минуты';
 if(d<3600)return Math.floor(d/60)+' мин';
 return Math.floor(d/3600)+' ч '+Math.floor(d%3600/60)+' мин';
}
export function stamp(seconds,time=true){
 return new Date(seconds*1000).toLocaleString('ru',{day:'numeric',month:'short',...(new Date(seconds*1000).getFullYear()!==new Date().getFullYear()?{year:'numeric'}:{}),...(time?{hour:'2-digit',minute:'2-digit'}:{})});
}
export function clock(seconds){return new Date(seconds*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'});}
export function dayLabel(seconds,now=new Date()){
 const date=new Date(seconds*1000),today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
 const diff=Math.round((today-new Date(date.getFullYear(),date.getMonth(),date.getDate()))/86400000);
 if(diff===0)return 'Сегодня';if(diff===1)return 'Вчера';
 return date.toLocaleDateString('ru',{weekday:'long',day:'numeric',month:'long'});
}
// "Chrome · Windows" from a User-Agent; enough for an owner to tell devices apart.
export function device(agent=''){
 const ua=String(agent);if(!ua)return 'Неизвестное устройство';
 const browser=/YaBrowser\//.test(ua)?'Яндекс Браузер':/Edg\//.test(ua)?'Edge':/OPR\//.test(ua)?'Opera':/Firefox\//.test(ua)?'Firefox':/Chrome\//.test(ua)?'Chrome':/Safari\//.test(ua)?'Safari':ua.split(/[\/ ]/)[0];
 const os=/iPhone/.test(ua)?'iPhone':/iPad/.test(ua)?'iPad':/Android/.test(ua)?'Android':/Windows/.test(ua)?'Windows':/Mac OS X|Macintosh/.test(ua)?'macOS':/Linux/.test(ua)?'Linux':'';
 return os?browser+' · '+os:browser;
}
export const CATEGORY_LABELS={video:'Видео',manga:'Манга',music:'Музыка',api:'Служебные запросы'};
export const EVENT_GROUPS=[
 ['all','Все'],
 ['watch','Просмотр',a=>/Открыл|Запустил/.test(a)],
 ['sign','Входы',a=>/Вош|парол|Зарегистр|Вход/.test(a)],
 ['access','Доступ',a=>/закрыт/.test(a)],
 ['address','IP',a=>/IP/.test(a)],
];
export function eventTone(action){
 if(/Неверный|отклон|закрыт/.test(action))return 'is-warn';
 if(/IP/.test(action))return 'is-info';
 return '';
}
