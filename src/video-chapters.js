// Video chapters: scenes the server marks up from subtitles, or a chapter file
// the viewer brings (Matroska XML, WebVTT chapters, OGM, FFmetadata, YouTube list).
// A chapter is {start, title}; its end is the next start or the video's end.
import {useCallback,useEffect,useRef,useState} from 'react';
import {collapsSelection} from './collaps-direct.js';

const clean=value=>String(value??'').replace(/\s+/g,' ').trim();

// "1:02:03.5", "02:03", "00:00:01,250", "83" → seconds.
export function chapterSeconds(value){
 const text=clean(value).replace(',','.');
 if(/^\d+(?:\.\d+)?$/.test(text))return Number(text);
 const m=/^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$/.exec(text);
 return m?Number(m[1]||0)*3600+Number(m[2])*60+Number(m[3]):NaN;
}

// Sorted, one chapter per start, inside the video.
export function normalizeChapters(rows,duration=Infinity){
 const out=[];
 for(const row of [...(rows||[])].filter(r=>Number.isFinite(r?.start)&&r.start>=0&&r.start<duration).sort((a,b)=>a.start-b.start)){
  const title=clean(row.title).slice(0,120);
  if(out.length&&row.start-out.at(-1).start<1)continue;
  out.push({start:Math.round(row.start*1000)/1000,title:title||'Глава '+(out.length+1)});
 }
 if(out.length&&out[0].start>0&&out[0].start<2)out[0].start=0;
 return out;
}

const elements=(node,name)=>[...node.childNodes].filter(n=>n.nodeType===1&&n.tagName===name);
function matroska(text){
 const doc=new DOMParser().parseFromString(text,'application/xml');
 if(doc.getElementsByTagName('parsererror').length)throw Error('Файл глав Matroska повреждён.');
 const editions=[...doc.getElementsByTagName('EditionEntry')];
 const edition=editions.find(e=>e.getElementsByTagName('EditionFlagDefault')[0]?.textContent.trim()==='1')||editions[0];
 if(!edition)throw Error('В файле Matroska нет глав.');
 return elements(edition,'ChapterAtom').filter(atom=>atom.getElementsByTagName('ChapterFlagHidden')[0]?.textContent.trim()!=='1').map(atom=>{
  const displays=elements(atom,'ChapterDisplay');
  const pick=displays.find(d=>/^(rus|ru)$/i.test(d.getElementsByTagName('ChapterLanguage')[0]?.textContent.trim()||d.getElementsByTagName('ChapLanguageIETF')[0]?.textContent.trim()||''))||displays[0];
  return {start:chapterSeconds(atom.getElementsByTagName('ChapterTimeStart')[0]?.textContent||''),title:pick?.getElementsByTagName('ChapterString')[0]?.textContent||''};
 });
}

function webvtt(text){
 const rows=[],lines=text.replace(/\r\n?/g,'\n').split('\n');
 for(let i=0;i<lines.length;i++){
  const m=/^\s*([\d:.,]+)\s+-->\s+([\d:.,]+)/.exec(lines[i]);if(!m)continue;
  const body=[];for(i++;i<lines.length&&lines[i].trim();i++)body.push(lines[i].replace(/<[^>]+>/g,''));
  rows.push({start:chapterSeconds(m[1]),title:body.join(' ')});
 }
 return rows;
}

function ogm(text){
 const times={},names={};
 for(const line of text.split(/\r?\n/)){
  const m=/^CHAPTER(\d+)(NAME)?=(.*)$/i.exec(line.trim());if(!m)continue;
  (m[2]?names:times)[m[1]]=m[3];
 }
 return Object.keys(times).map(k=>({start:chapterSeconds(times[k]),title:names[k]||''}));
}

function ffmetadata(text){
 const rows=[];let row=null,base=1/1000;
 for(const raw of text.split(/\r?\n/)){
  const line=raw.trim();
  if(line==='[CHAPTER]'){row={};rows.push(row);base=1/1000;continue;}
  if(!row||!line.includes('='))continue;
  const key=line.slice(0,line.indexOf('=')).toUpperCase(),value=line.slice(line.indexOf('=')+1).replace(/\\(.)/g,'$1');
  if(key==='TIMEBASE'){const [a,b]=value.split('/').map(Number);if(a>0&&b>0)base=a/b;row.base=base;}
  else if(key==='START')row.raw=Number(value);
  else if(key==='TITLE')row.title=value;
 }
 return rows.map(r=>({start:(r.raw??NaN)*(r.base??1/1000),title:r.title||''}));
}

// "00:00 Пролог" lines, as YouTube descriptions and Chaptergen print them.
function plainList(text){
 return text.split(/\r?\n/).map(line=>/^\s*\(?((?:\d+:)?\d{1,2}:\d{2})\)?\s*[-–—:.]?\s+(.+)$/.exec(line)).filter(Boolean).map(m=>({start:chapterSeconds(m[1]),title:m[2]}));
}

export function parseChapterFile(text,duration){
 const value=String(text||'').replace(/^﻿/,'').trim();
 let rows;
 if(/^(<\?xml[^>]*>\s*)?(<!DOCTYPE[^>]*>\s*)?<Chapters\b/i.test(value))rows=matroska(value);
 else if(/^WEBVTT/.test(value))rows=webvtt(value);
 else if(/^;FFMETADATA1/.test(value))rows=ffmetadata(value);
 else if(/^CHAPTER\d+=/im.test(value))rows=ogm(value);
 else rows=plainList(value);
 const chapters=normalizeChapters(rows,duration||Infinity);
 if(!chapters.length)throw Error('В файле не нашлось глав. Подходят Matroska XML, WebVTT, OGM, FFmetadata и список «00:00 Название».');
 return chapters;
}

export const chapterIndexAt=(chapters,time)=>{let i=-1;for(let n=0;n<chapters.length&&chapters[n].start<=time+.05;n++)i=n;return i;};
export function chapterSpans(chapters,duration){
 return chapters.filter(c=>c.start<duration).map((c,i,list)=>({...c,end:Math.min(duration,list[i+1]?.start??duration)}));
}

const two=n=>String(Math.floor(n)).padStart(2,'0');
export function chapterClock(seconds,fraction=3){
 const ms=Math.max(0,Math.round(seconds*1000));
 const whole=two(ms/3600000)+':'+two(ms/60000%60)+':'+two(ms/1000%60);
 return fraction===9?whole+'.'+String(ms%1000).padStart(3,'0')+'000000':whole+'.'+String(ms%1000).padStart(3,'0');
}
const xml=value=>String(value).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function uid(seed){let h=1469598103934665603n;for(const c of seed)h=BigInt.asUintN(63,(h^BigInt(c.codePointAt(0)))*1099511628211n);return (h||1n).toString();}

export function toMatroskaXml(chapters,duration,seed='mediavault'){
 return ['<?xml version="1.0" encoding="UTF-8"?>','<!DOCTYPE Chapters SYSTEM "matroskachapters.dtd">','<Chapters>','  <EditionEntry>','    <EditionFlagDefault>1</EditionFlagDefault>','    <EditionUID>'+uid(seed+':edition')+'</EditionUID>',
  ...chapterSpans(chapters,duration).flatMap((c,i)=>['    <ChapterAtom>','      <ChapterUID>'+uid(seed+':'+i)+'</ChapterUID>','      <ChapterTimeStart>'+chapterClock(c.start,9)+'</ChapterTimeStart>','      <ChapterTimeEnd>'+chapterClock(c.end,9)+'</ChapterTimeEnd>',
   '      <ChapterFlagEnabled>1</ChapterFlagEnabled>','      <ChapterDisplay>','        <ChapterString>'+xml(c.title)+'</ChapterString>','        <ChapterLanguage>rus</ChapterLanguage>','        <ChapLanguageIETF>ru</ChapLanguageIETF>','      </ChapterDisplay>','    </ChapterAtom>']),
  '  </EditionEntry>','</Chapters>',''].join('\n');
}
export function toWebVttChapters(chapters,duration){
 return 'WEBVTT\n\n'+chapterSpans(chapters,duration).map((c,i)=>(i+1)+'\n'+chapterClock(c.start)+' --> '+chapterClock(c.end)+'\n'+c.title.replace(/-->/g,'→')).join('\n\n')+'\n';
}

// Collaps embeds the voices of this title came from: the server reads their subtitle list.
export function collapsEmbeds(voices,season,episode){
 const out=new Set();
 for(const v of voices||[])for(const variant of v.variants||[])for(const url of [variant.url,variant.sourceUrl]){
  const hit=url&&collapsSelection(url);if(!hit)continue;
  const next=new URL(hit.embed);if(season)next.searchParams.set('mv_season',season);if(episode)next.searchParams.set('mv_episode',episode);
  out.add(next.href);if(out.size>=4)return [...out];
 }
 return [...out];
}

// The subtitle track worth sending for chapters: Russian full first, never "forced"/"signs".
export function chapterSubtitlePick(options){
 const usable=(options||[]).filter(o=>o.value&&o.value!=='off'&&!/форс|forced|надпис|sign/i.test(o.label||''));
 return usable.find(o=>/рус|rus/i.test(o.label||''))||usable[0]||null;
}

const memory=new Map();
// One request per episode; the server answers from its record when one exists.
export function useVideoChapters({service,enabled=true,request}){
 const key=request?[request.work,request.season||0,request.episode||0].join('|'):'';
 const [value,setValue]=useState(()=>memory.get(key)||{state:key?'loading':'off',chapters:[]});
 const live=useRef(request);live.current=request;
 const sent=useRef(new Set());
 useEffect(()=>{
  if(!enabled||!key||!service?.request){setValue({state:'off',chapters:[]});return;}
  setValue(memory.get(key)||{state:'loading',chapters:[]});
  let closed=false,timer=0,rounds=0;
  const ask=async(body)=>{
   try{
    const data=await service.request('/video-chapters/prepare',{method:'POST',body});
    if(closed)return;
    const next={state:data.state,chapters:normalizeChapters(data.chapters||[]),source:data.source||'',reason:data.reason||'',key:data.key,rank:data.rank||0};
    if(data.state==='ready'||data.state==='none')memory.set(key,next);
    setValue(next);
    if((data.state==='working'||data.state==='busy')&&rounds++<60)timer=setTimeout(()=>ask(live.current),Math.min(8000,2000+rounds*400));
   }catch{if(!closed)setValue({state:'error',chapters:[]});}
  };
  ask(live.current);
  return()=>{closed=true;clearTimeout(timer);};
 },[key,enabled,service]);
 // The player found subtitles of its own (Alloha, HLS, a local file): better
 // aligned with this very video than a library file, so the server may redo it.
 const submit=useCallback(async(subtitle)=>{
  if(!enabled||!key||!service?.request||!subtitle?.text||sent.current.has(key))return;
  if(memory.get(key)?.state==='ready'&&memory.get(key).rank>=3)return;
  sent.current.add(key);
  try{
   const data=await service.request('/video-chapters/prepare',{method:'POST',body:{...live.current,subtitle}});
   let next={state:data.state,chapters:normalizeChapters(data.chapters||[]),source:data.source||'',key:data.key,rank:data.rank||0};
   for(let i=0;next.state==='working'&&i<40;i++){
    await new Promise(r=>setTimeout(r,2500));
    const poll=await service.request('/video-chapters/prepare',{method:'POST',body:live.current});
    next={state:poll.state,chapters:normalizeChapters(poll.chapters||[]),source:poll.source||'',key:poll.key,rank:poll.rank||0};
   }
   if(next.state==='ready'){memory.set(key,next);setValue(next);}
  }catch{/* chapters stay as they were */}
 },[key,enabled,service]);
 return {...value,submit};
}
