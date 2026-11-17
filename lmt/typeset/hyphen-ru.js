// SPDX-License-Identifier: AGPL-3.0-or-later
// Syllable hyphenation for Russian (Khristoforov's rule set). Returns the
// fragments a word may be split into; never leaves a single letter or a
// fragment without a vowel, and reuses an existing hyphen instead of adding one.
const X='йьъ',G='аеёиоуыэюя',S='бвгджзклмнпрстфхцчшщ';
const RULES=[
 [`[${X}]`,`[${G}${S}][${G}${S}]`],
 [`[${G}]`,`[${G}][${G}${S}]`],
 [`[${G}][${S}]`,`[${S}][${G}]`],
 [`[${S}][${G}]`,`[${S}][${G}]`],
 [`[${G}][${S}]`,`[${S}][${S}][${G}]`],
 [`[${G}][${S}][${S}]`,`[${S}][${S}][${G}]`],
].map(([a,b])=>new RegExp(`(${a})(?=${b})`,'gi'));
const hasVowel=part=>new RegExp(`[${G}]`,'i').test(part);
const letters=part=>(part.match(/[а-яё]/gi)||[]).length;
export function hyphenate(word){
 if(word.includes(' '))return [word];
 if(/[а-яёa-z]-[а-яёa-z]/i.test(word)){const parts=word.split(/(?<=-)/);return parts.every(p=>letters(p)>=2)?parts:[word];}
 if(letters(word)<5)return [word];
 let marked=word;
 for(let pass=0;pass<2;pass++)for(const rule of RULES)marked=marked.replace(rule,'$1­');
 const raw=marked.split('­'),parts=[];
 for(const piece of raw){
  const last=parts.length-1;
  if(last>=0&&(letters(parts[last])<2||!hasVowel(parts[last])))parts[last]+=piece;else parts.push(piece);
 }
 while(parts.length>1&&(letters(parts.at(-1))<2||!hasVowel(parts.at(-1)))){const tail=parts.pop();parts[parts.length-1]+=tail;}
 return parts;
}
