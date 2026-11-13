import policy from '../server/manga-tag-policy.json' with {type:'json'};
export const tagLabels=Object.fromEntries(policy.tags.flatMap(row=>row.aliases.filter(alias=>alias!==row.label).map(alias=>[alias,row.label])));
const labelKey=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
const caseLabels=new Map(Object.entries(tagLabels).flatMap(([key,label])=>[[labelKey(key),label],[labelKey(label),label]]));
export const localLabel=value=>tagLabels[value]||caseLabels.get(labelKey(value))||value;
export const queryLabel=value=>Object.entries(tagLabels).find(([,ru])=>ru.toLocaleLowerCase()===String(value).toLocaleLowerCase())?.[0]||value;
export const russianLabels=values=>[...new Set((values||[]).map(localLabel).filter(v=>/[а-яё]/i.test(v)))];
