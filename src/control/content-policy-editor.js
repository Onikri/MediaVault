import {compileMangaPolicy,normalizeTag} from '../manga-tag-policy.js';

export const pastedLabels=text=>[...new Set(String(text||'').split(/[\n;]+/).map(value=>value.trim()).filter(Boolean))];
export function addContentLabels(policy,text,category){
 const next=structuredClone(policy);compileMangaPolicy(next);let added=0;
 for(const label of pastedLabels(text)){
  if(label.length>120||!normalizeTag(label))throw Error('Название должно содержать от 1 до 120 символов.');
  const existing=next.tags.find(row=>[row.key,row.label,...row.aliases].some(value=>normalizeTag(value)===normalizeTag(label)));
  if(existing)continue;
  const row={key:normalizeTag(label),label,aliases:[label],...(category?{category}:{})};
  next.tags.push(row);added++;
 }
 compileMangaPolicy(next);return {policy:next,added};
}
export function updateContentRule(policy,key,changes){
 const next={...policy,tags:policy.tags.map(row=>row.key===key?{...row,...changes}:row)};
 compileMangaPolicy(next);return next;
}

