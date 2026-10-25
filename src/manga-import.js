export function chapterRanges(text){
 if(!text||String(text).toLowerCase()==='all')return null;
 return String(text).split(',').map(value=>{const m=value.match(/^\s*(\d+(?:\.\d{1,3})?)(?:\s*-\s*(\d+(?:\.\d{1,3})?))?\s*$/);if(!m)throw Error('Укажи главы: 0, 1-20, 12.5.');const a=Number(m[1]),b=Number(m[2]||m[1]);if(b<a||b>=10000)throw Error('Проверь диапазон глав.');return [a,b];});
}
export function selectChapters(entries,{volume='all',team='',selection='all'}={}){
 const ranges=chapterRanges(selection),eligible=entries.filter(e=>e.language==='ru'&&Number.isFinite(e.number)&&e.number>=0&&e.number<10000&&(volume==='all'||Number(e.season)===Number(volume))&&(!team||e.translator===team)&&(!ranges||ranges.some(([a,b])=>e.number>=a&&e.number<=b)));
 return [...new Map(eligible.map(e=>[Number(e.season||1)+':'+e.number,e])).values()].sort((a,b)=>Number(a.season||1)-Number(b.season||1)||a.number-b.number);
}
export function mangaMetadata(item){return item?Object.fromEntries(['title','titles','aliases','description','cover','year','format','genres','tags','age','ageLabel','chapters','volumes','status','startDate','endDate','ids','links','kind'].map(k=>[k,item[k]])):{};}
