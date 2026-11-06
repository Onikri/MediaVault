// Which player a dub plays from: a short tag with its own tint, shown next to the dub.
// Names come from the server's variant.player (player_catalog.player_name, balancer
// button titles, dynamic sources) and are matched loosely.
const SOURCES=[
  ['alloha',/alloha/i,'Alloha',150],
  ['kodik',/kodik/i,'Kodik',28],
  ['sibnet',/sibnet/i,'Sibnet',205],
  ['cvh',/\bcvh\b|cdnvideohub/i,'CVH',265],
  ['vk',/\bvk\b|vk ?video|vkvideo/i,'VK',215],
  ['aniboom',/aniboom/i,'Aniboom',330],
  ['kinopoisk',/kinopoisk|кинопоиск|\bkp\b/i,'Кинопоиск',38],
  ['collaps',/collaps|коллапс/i,'Collaps',180],
  ['vibix',/vibix/i,'Vibix',290],
  ['lumex',/lumex|lumix/i,'Lumex',55],
  ['turbo',/turbo/i,'Turbo',0],
  ['videoseed',/videoseed|viveo/i,'VideoSeed',120],
  ['aniliberty',/anilibr|aniliberty/i,'AniLibria',345],
  ['anistar',/anistar/i,'AniStar',245],
  ['jutsu',/jut\.?su/i,'Jut.su',95],
  ['animedia',/animedia/i,'Animedia',310],
  ['hentasis',/hentasis/i,'Hentasis',320],
  ['hanime',/hanime/i,'Hanime',335]
];
export function sourceOf(player){
  const name=String(player||'').trim();if(!name)return null;
  const hit=SOURCES.find(([,re])=>re.test(name));
  if(hit)return {key:hit[0],label:hit[2],hue:hit[3]};
  const short=name.replace(/\s*\(.*\)\s*$/,'').replace(/^www\./,'').replace(/\.[a-z]{2,}$/i,'');
  return {key:short.toLowerCase(),label:short.slice(0,14),hue:null};
}
// Distinct sources a dub can play from, in the order the server ranks its variants.
export function sourcesOfVoice(voice){
  const seen=new Map();
  for(const v of voice?.variants||[]){const s=sourceOf(v.player);if(s&&!seen.has(s.key))seen.set(s.key,s);}
  return [...seen.values()];
}
export function SourceBadges({sources,max=3}){
  if(!sources?.length)return null;
  const shown=sources.slice(0,max),rest=sources.length-shown.length;
  return <span className="mvx-sources" aria-label={'Источник: '+sources.map(s=>s.label).join(', ')}>
    {shown.map(s=><span key={s.key} className="mvx-source" style={s.hue===null?undefined:{'--source-hue':s.hue}}>{s.label}</span>)}
    {rest>0&&<span className="mvx-source is-more">+{rest}</span>}
  </span>;
}
