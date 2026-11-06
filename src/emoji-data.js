// A compact, curated emoji set for the room chat: enough for reactions and
// conversation without shipping a full Unicode catalogue.
const split=value=>[...new Intl.Segmenter('ru',{granularity:'grapheme'}).segment(value)].map(s=>s.segment).filter(s=>s.trim());
export const EMOJI_GROUPS=[
 {id:'faces',label:'Смайлы',items:split('😀😃😄😁😆😅🤣😂🙂🙃😉😊😇🥰😍🤩😘😗😚😙😋😛😜🤪😝🤑🤗🤭🤫🤔🤐🤨😐😑😶😏😒🙄😬😮‍💨🤥😌😔😪🤤😴😷🤒🤕🤢🤮🥵🥶🥴😵🤯🤠🥳🥸😎🤓🧐😕😟🙁☹️😮😯😲😳🥺🥹😦😧😨😰😥😢😭😱😖😣😞😓😩😫🥱😤😡😠🤬😈👿💀☠️💩🤡👻👽🤖😺😸😹😻😼😽🙀😿😾')},
 {id:'hands',label:'Жесты',items:split('👍👎👌🤌🤏✌️🤞🫰🤟🤘🤙👈👉👆👇☝️👋🤚🖐️✋🖖👏🙌🫶👐🤲🤝🙏✍️💪🦾🫡🫣🫢🙈🙉🙊')},
 {id:'hearts',label:'Сердца',items:split('❤️🧡💛💚💙💜🖤🤍🤎💔❤️‍🔥❤️‍🩹💕💞💓💗💖💘💝💟♥️💯💢💥💫💦💨🕳️💬💭💤')},
 {id:'nature',label:'Природа',items:split('🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮🐷🐸🐵🐔🐧🐦🐤🦆🦅🦉🦇🐺🐗🐴🦄🐝🦋🐌🐞🐢🐍🐙🦑🦀🐬🐳🦈🐊🌸🌹🌺🌻🌼🌷🌱🌲🌴🌵🍀🍁🍂🌙⭐🌟✨⚡🔥🌈☀️⛅🌧️❄️☃️🌊')},
 {id:'food',label:'Еда',items:split('🍏🍎🍐🍊🍋🍌🍉🍇🍓🫐🍒🍑🥭🍍🥥🥝🍅🥑🌶️🌽🥕🥐🍞🧀🍳🥓🍔🍟🍕🌭🥪🌮🌯🍜🍝🍣🍱🥟🍙🍚🍛🍤🍡🍦🍩🍪🎂🍰🧁🍫🍬🍭🍿☕🍵🧋🥤🍺🍻🥂🍷🍸🍹')},
 {id:'fun',label:'Досуг',items:split('🎉🎊🎈🎁🏆🥇🎮🕹️🎲🧩🎯🎳🎤🎧🎸🎹🥁🎬🍿📺📽️🎞️📸💡📌🔔🎵🎶⚽🏀🏐🎾🏓🥊🛹🚀✈️🚗🏠🌃🗾🗻⛩️🎌🍥')},
 {id:'symbols',label:'Символы',items:split('✅❌❓❗‼️⁉️⚠️🚫⛔💤🆗🆒🆕🆙🔝🔜♻️✔️➕➖➗✖️💲💰🔞📢📣🔇🔊⏸️▶️⏩⏪⏫⏬🔁🔂🔀⏱️⌛⏳🕐')},
];
export const QUICK_REACTIONS=['👍','😂','❤️','🔥','😮','😢'];
const RECENT_KEY='mv-recent-emoji';
export function recentEmoji(){try{const v=JSON.parse(localStorage.getItem(RECENT_KEY)||'[]');return Array.isArray(v)?v.filter(x=>typeof x==='string').slice(0,24):[];}catch{return [];}}
export function rememberEmoji(value){try{localStorage.setItem(RECENT_KEY,JSON.stringify([value,...recentEmoji().filter(x=>x!==value)].slice(0,24)));}catch{}}
// "Emoji only" messages (up to three) are shown large, like in Telegram.
export function jumboEmoji(text){
 const value=String(text||'').trim();if(!value||value.length>40)return false;
 if(!/^[\p{Extended_Pictographic}\p{Emoji_Component}‍️\s]+$/u.test(value)||/^[\d#*\s]+$/.test(value))return false;
 return split(value).length<=3;
}
