// Pure playback catalog helpers. No network requests or decrypted media data are persisted.
const video = item => item?.category === 'video';
const numeric = value => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null;

export function episodeNumber(item) {
  const explicit = numeric(item.episode);
  if (explicit) return explicit;
  const stem = String(item.name || '').replace(/\.[^.]+$/, '');
  const match = stem.match(/(?:^|[\s._-])s\d{1,3}e(\d{1,4})(?=$|[\s._-])/i) ||
    stem.match(/(?:^|[\s._-])(?:episode|ep|серия|эпизод)[\s._-]*(\d{1,4})(?=$|[\s._-])/i) ||
    stem.match(/^0*(\d{1,4})(?=$|[\s._-])/);
  return match ? numeric(match[1]) : null;
}
export function voiceLabel(item, fallback = 'Оригинал') {
  for (const key of ['voice', 'dub', 'dubbing', 'translation', 'audioLabel']) {
    if (typeof item[key] === 'string' && item[key].trim()) return item[key].trim().slice(0, 80)+(item.translationInfo?.kind==='subtitles'?' · субтитры':'');
  }
  const bracket = String(item.name || '').match(/[\[(]([^\])]{2,60})[\])]/);
  return bracket ? bracket[1].trim() : fallback;
}
export function buildPlaybackLibrary(current, catalog) {
  const group = (catalog?.storage?.collections || []).find(entry => entry.id === current.collectionId);
  const identity=group?.metadataId||group?.metadata?.ids?.mal||catalog?.titleProfiles?.[(current.section||'anime')+':'+group?.id]?.sourceId;
  const matchingGroups=(catalog?.storage?.collections||[]).filter(g=>g.id===group?.id||identity&&g.section===group?.section&&String(g.metadataId||g.metadata?.ids?.mal||catalog?.titleProfiles?.[(current.section||'anime')+':'+g.id]?.sourceId||'')===String(identity));
  const collectionIds=new Set(matchingGroups.map(g=>g.id));
  const assets = (catalog?.items || []).filter(item => video(item) &&
    (current.collectionId ? collectionIds.has(item.collectionId) : item.id === current.id));
  if (!assets.some(item => item.id === current.id)) assets.push(current);
  const partNames = new Map(matchingGroups.flatMap(g=>g.parts||[]).map(part => [part.id, part.name]));
  const seasons = new Map();
  for (const item of assets) {
    const part = partNames.get(item.partId) || item.partName ||
      (numeric(item.season) ? 'Сезон ' + item.season : 'Эпизоды');
    const key = matchingGroups.length>1?part:item.partId || part;
    if (!seasons.has(key)) seasons.set(key, {id: key, name: part, episodes: new Map()});
    const season = seasons.get(key);
    const number = episodeNumber(item);
    const episodeKey = number === null ? 'file:' + item.id : 'episode:' + number;
    if (!season.episodes.has(episodeKey)) season.episodes.set(episodeKey, {
      id: episodeKey,number,description:item.episodeDescription||'',label: item.episodeTitle|| (number === null ? item.name : 'Эпизод ' + number), variants: []
    });
    const episode = season.episodes.get(episodeKey);
    episode.variants.push({item, label: voiceLabel(item, 'Версия ' + (episode.variants.length + 1))});
  }
  return {
    title: catalog?.titleProfiles?.[(current.section||'video')+':'+(group?.id||'file-'+current.id)]?.title || group?.metadata?.titles?.ru || group?.name || current.name,
    seasons: [...seasons.values()].map(part => ({
      id: part.id, name: part.name,
      episodes: [...part.episodes.values()].sort((a,b) => (a.number ?? Infinity) - (b.number ?? Infinity) ||
        a.label.localeCompare(b.label, 'ru', {numeric: true}))
    })).sort((a,b) => a.name.localeCompare(b.name,'ru',{numeric:true}))
  };
}
export function openingBounds(value, duration = Infinity) {
  const pair = Array.isArray(value) ? value : value && typeof value === 'object' ? [value.start, value.end] : [];
  const start = Number(pair[0]), end = Number(pair[1]);
  return pair.length === 2 && Number.isFinite(start) && Number.isFinite(end) &&
    start >= 0 && end > start && end <= duration ? {start,end} : null;
}
export function toWebVtt(contents, name = '') {
  const text = String(contents).replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').trim();
  if (/^WEBVTT(?:\s|$)/.test(text)) return text + '\n';
  if (!/\.srt$/i.test(name)) throw Error('Поддерживаются только SRT и VTT.');
  const normalized = text.replace(/(\d\d:\d\d:\d\d),(\d{3})\s*-->\s*(\d\d:\d\d:\d\d),(\d{3})/g,
    '$1.$2 --> $3.$4');
  if (!/\d\d:\d\d:\d\d\.\d{3}\s*-->/.test(normalized)) throw Error('В файле SRT нет корректных таймкодов.');
  return 'WEBVTT\n\n' + normalized + '\n';
}
