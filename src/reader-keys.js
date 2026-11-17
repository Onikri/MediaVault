// Keyboard matching shared by the player, the readers and the key sheet.
// Letters match by the physical key too (event.code), so N, F or K work on a
// Russian layout as well; «?» is Shift+/ on English and Shift+7 on Russian.
export const isHelpKey=event=>event.key==='?'||(event.code==='Slash'&&event.shiftKey);
export const keyIs=(...names)=>event=>names.some(name=>name.length===1?String(event.key||'').toLowerCase()===name||event.code==='Key'+name.toUpperCase():event.key===name||event.code===name);
