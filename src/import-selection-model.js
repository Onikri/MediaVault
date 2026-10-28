export function selectedVideoEntries(entries,selection='all'){
 const value=String(selection||'all').trim();if(value==='all')return entries;
 const ranges=value.split(',').map(part=>{const match=/^\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*$/.exec(part);if(!match)throw Error('Укажи номера серий: 1, 3, 5-8.');const first=Number(match[1]),last=Number(match[2]||match[1]);if(first<1||last<first)throw Error('Проверь начало и конец диапазона серий.');return [first,last];});
 return entries.filter(entry=>ranges.some(([first,last])=>entry.number>=first&&entry.number<=last));
}
