const bytes=Uint8Array.from({length:256},(_,index)=>index);
const utf8=new TextDecoder('utf-8',{fatal:true});
const alphabets=['windows-1252','windows-1251'].map(encoding=>{
 const chars=new TextDecoder(encoding).decode(bytes),map=new Map();
 for(let index=0;index<chars.length;index++)if(!map.has(chars[index]))map.set(chars[index],index);
 return map;
});
const odd=/[Ѓ‚љњћџђѓєѕіїјќў€™]/gu;
const badness=value=>{
 const controls=(value.match(/[\u0000-\u001f\u007f-\u009f\ufffd]/gu)||[]).length;
 const latin=(value.match(/(?:[ÐÑ][^\s]){2,}/gu)||[]).length;
 const cyrillic=(value.match(/(?:[РС][^\s]){2,}/gu)||[]).length;
 return controls*20+latin*12+cyrillic*12+(value.match(odd)||[]).length*3;
};
function recode(value,map){
 const data=[];
 for(const char of value){const byte=map.get(char);if(byte==null)return null;data.push(byte);}
 try{return utf8.decode(Uint8Array.from(data));}catch{return null;}
}
export function readableCatalogLabel(value){
 if(typeof value!=='string')return '';
 let best=value.replace(/^[\s,;|]+|[\s,;|]+$/gu,'');
 for(let pass=0;pass<3;pass++){
  const choices=[best,...alphabets.map(map=>recode(best,map)).filter(Boolean)];
  choices.sort((a,b)=>badness(a)-badness(b)||[...b].filter(c=>/\p{L}/u.test(c)).length-[...a].filter(c=>/\p{L}/u.test(c)).length||a.length-b.length);
  if(badness(choices[0])>=badness(best))break;
  best=choices[0];
 }
 return best.replace(/\s+/gu,' ').trim().slice(0,120);
}
export const readableCatalogLabels=values=>[...new Set((values||[]).map(readableCatalogLabel).filter(Boolean))];
