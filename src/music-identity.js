// Separate catalogue identity from a noisy upload/video caption. No guessed transliteration.
const text=v=>String(v||'').normalize('NFKC').replace(/[\u0000-\u001f]/g,' ').replace(/\s+/g,' ').trim().slice(0,300);
export const musicName=v=>text(v).toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
const unique=values=>[...new Map(values.filter(Boolean).map(v=>[musicName(v),v])).values()];
const service=v=>text(v).replace(/\s*[-–—]\s*Topic$/i,'').replace(/\s*\b(?:official\s+)?(?:music\s+video|video|audio|lyrics|lyric\s+video|MV|HD|4K)\b\s*$/i,'').trim();
function artistParts(value){const raw=service(value),brackets=[...raw.matchAll(/[([（【]([^\])）】]+)[\])）】]/g)].map(m=>service(m[1])),outside=raw.replace(/[([（【][^\])）】]*[\])）】]/g,' ').trim(),scripts=outside.match(/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}ー]+|[\p{Script=Latin}\p{N}][\p{Script=Latin}\p{N}\s.'’&-]*/gu)||[];return unique([outside,...brackets,...scripts.map(text)]);}
export function musicIdentity(track={}){
 const artists=unique((track.artists||[]).flatMap(artistParts)).filter(v=>musicName(v).length>1),ordered=[...artists].sort((a,b)=>b.length-a.length);
 const cleanTitle=value=>{let title=text(value).replace(/[「『“”"']/g,'').replace(/\[(?:official[^\]]*|music video|MV|HD|4K)\]|\((?:official[^)]*|music video|MV|HD|4K)\)/gi,' ');
  for(let n=0;n<8;n++){let next=title;for(const artist of ordered){const escaped=artist.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');next=next.replace(new RegExp('^'+escaped+'(?:\\s*[-–—:|/]+\\s*|\\s+)','i'),'').replace(new RegExp('(?:\\s*[-–—:|/]+\\s*|\\s+)[(（]?'+escaped+'[)）]?$','i'),'').trim();}next=next.replace(/^[\s\-–—:|/]+|[\s\-–—:|/]+$/g,'').replace(/\s+/g,' ');if(next===title)break;title=next;}
  return service(title)||text(value);
 };
 const titleForms=value=>{const full=cleanTitle(value),parts=[...full.matchAll(/[（(]([^）)]+)[）)]/g)].map(m=>text(m[1]));const alternate=parts.filter(p=>!versions(p)&&/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u.test(p)!==/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u.test(full.replace(/[（(][^）)]+[）)]/g,'')));const base=alternate.length?full.replace(/[（(][^）)]+[）)]/g,'').trim():full;return [base,...alternate,full];};
 const titles=unique([track.title,...track.aliases||[]].flatMap(titleForms)).slice(0,6),displayArtist=artists.find(a=>/[A-Za-z]/.test(a)&&!/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u.test(a))||artists[0]||'';
 return {title:titles[0]||text(track.title),titles,artists,artist:displayArtist,album:text(track.album),year:String(track.year||track.date||'').slice(0,4),aliases:titles.slice(1)};
}
const versions=v=>['cover','live','remix','instrumental','slowed','sped','nightcore','tv size','tv-size','short','karaoke'].filter(w=>text(v).toLowerCase().includes(w)).sort().join('|');
export function rankLyricRecord(record,identity,duration,{allowVideoPadding=false}={}){
 if(!record||record.instrumental||!Number.isFinite(Number(record.duration))||Math.abs(Number(record.duration)-duration)>(allowVideoPadding?Math.min(20,Math.max(10,duration*.08)):2.5))return -1;
 const row=musicIdentity({title:record.trackName,artists:[record.artistName]}),titleMatch=identity.titles.some(t=>musicName(t)===musicName(row.title)),artistMatch=row.artists.some(a=>identity.artists.some(b=>musicName(a)===musicName(b)));
 if(!titleMatch||!artistMatch||versions(record.trackName)!==versions(identity.title))return -1;
 return 200-Math.abs(Number(record.duration)-duration)*5+(record.syncedLyrics?40:record.plainLyrics?5:-300)+(identity.album&&musicName(identity.album)===musicName(record.albumName)?10:0);
}
