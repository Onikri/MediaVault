import {musicIdentity} from './music-identity.js';
// Real timestamps only: standard LRC is line-synced, Enhanced LRC/TTML can be word-synced.
const stamp=value=>{const s=String(value||'').trim();if(/^\d+(?:\.\d+)?s$/.test(s))return Number(s.slice(0,-1));if(/^\d+(?:\.\d+)?ms$/.test(s))return Number(s.slice(0,-2))/1000;const p=s.split(':').map(Number);return p.length>=2&&p.length<=3&&p.every(Number.isFinite)?p.reduce((a,n)=>a*60+n,0):NaN;};
const valid=n=>Number.isFinite(n)&&n>=0&&n<=7200;
const lrcStamp=value=>stamp(value.replace(/^(\d+:\d{2}):(\d{1,3})$/, '$1.$2'));
function finish(lines){
 const sorted=lines.filter(l=>valid(l.start)&&typeof l.text==='string').sort((a,b)=>a.start-b.start).slice(0,2000);
 for(let i=0;i<sorted.length;i++){const l=sorted[i];l.end=valid(l.end)&&l.end>l.start?l.end:sorted[i+1]?.start??l.start+10;l.words=(l.words||[]).map(w=>({...w,end:w.end??l.end})).filter(w=>valid(w.start)&&valid(w.end)&&w.end>w.start&&w.start>=l.start-.1&&w.end<=l.end+.1);}
 const visible=sorted.filter(l=>l.text.trim());return {lines:visible,precision:visible.some(l=>l.words.length)?'word':'line'};
}
export function parseLrc(text){
 if(typeof text!=='string'||text.length>1000000)throw Error('Текст песни слишком большой.');
 const offset=Number(text.match(/\[offset:([+-]?\d+)\]/i)?.[1]||0)/1000,lines=[];
 for(const raw of text.split(/\r?\n/)){const times=[...raw.matchAll(/\[(\d{1,3}:\d{2}(?:[.:]\d{1,3})?)\]/g)];if(!times.length)continue;const body=raw.slice((times.at(-1).index||0)+times.at(-1)[0].length),tags=[...body.matchAll(/<(\d{1,3}:\d{2}(?:[.:]\d{1,3})?)>/g)];
  for(const time of times){const start=lrcStamp(time[1])-offset,shift=start-(lrcStamp(times[0][1])-offset),words=[];for(let i=0;i<tags.length;i++){const t=tags[i],next=tags[i+1],word=body.slice(t.index+t[0].length,next?.index);if(word)words.push({text:word,start:lrcStamp(t[1])-offset+shift,end:next?lrcStamp(next[1])-offset+shift:undefined});}const last=tags.at(-1),tail=last?body.slice(last.index+last[0].length):'';lines.push({start,text:body.replace(/<[^>]*>/g,''),words,end:!tail.trim()&&last?lrcStamp(last[1])-offset+shift:undefined});}
 }return finish(lines);
}
export function parseTtml(text){
 if(typeof text!=='string'||text.length>1000000||/<!DOCTYPE|<!ENTITY/i.test(text))throw Error('Некорректный TTML.');
 const doc=new DOMParser().parseFromString(text,'application/xml');if(doc.querySelector('parsererror'))throw Error('Не удалось прочитать TTML.');
 const skipped=node=>Array.from(node.attributes||[]).some(a=>a.localName==='role'&&/translation|roman/i.test(a.value));
 const clean=node=>node.nodeType===3?node.textContent:skipped(node)?'':Array.from(node.childNodes).map(clean).join('');
 const lines=[];
 for(const p of Array.from(doc.getElementsByTagNameNS('*','p')).slice(0,2000)){const start=stamp(p.getAttribute('begin')),end=stamp(p.getAttribute('end')),words=[];
  const walk=node=>{if(node.nodeType===3)return;if(skipped(node))return;const begin=stamp(node.getAttribute?.('begin')),stop=stamp(node.getAttribute?.('end')),children=Array.from(node.children||[]);if(node!==p&&valid(begin)&&valid(stop)&&!children.some(c=>c.hasAttribute('begin'))){words.push({text:clean(node),start:begin,end:stop});return;}children.forEach(walk);};walk(p);
  lines.push({start,end,text:clean(p).trim(),words});
 }return finish(lines);
}
export function lyricIndex(lines,time){let low=0,high=lines.length-1,best=-1;while(low<=high){const m=(low+high)>>1;if(lines[m].start<=time){best=m;low=m+1;}else high=m-1;}return best>=0&&time<lines[best].end?best:-1;}
export const normalizeLyrics=lines=>finish(lines.map(l=>({start:Number(l.time??l.start),end:l.end,text:l.text??l.line??'',words:l.words||[]})));
export function lyricFragments(line){let cursor=0;const parts=[];for(let i=0;i<line.words.length;i++){const w=line.words[i],at=line.text.indexOf(w.text,cursor);if(at<0)return [{text:line.text}];if(at>cursor)parts.push({text:line.text.slice(cursor,at)});parts.push({text:w.text,word:i});cursor=at+w.text.length;}if(cursor<line.text.length)parts.push({text:line.text.slice(cursor)});return parts;}
export const lyricName=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
export function matchLyricRecord(rows,track){const identity=musicIdentity(track),titles=identity.titles.map(lyricName),artists=identity.artists.map(lyricName);return rows.filter(r=>{const m=Object.fromEntries(r.metadata||[]);return (m.musicName||[]).some(t=>titles.includes(lyricName(t)))&&(m.artists||[]).some(a=>artists.includes(lyricName(a)))&&/^[\w-]+\.ttml$/.test(r.rawLyricFile||'');}).reverse().slice(0,3);}
