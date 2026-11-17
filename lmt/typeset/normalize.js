// SPDX-License-Identifier: AGPL-3.0-or-later
// Text preparation for Russian manga lettering. Pure; no DOM.
export const NBSP=' ';
const PREPOSITIONS=new Set('в во на к ко с со у о об от до из за по под над при про для без через между перед и а но да или что как'.split(' '));
const TRAILING_PARTICLES=new Set('бы б ли ль же ж уж'.split(' '));
const LEADING_PARTICLES=new Set(['не','ни']);
const bare=word=>word.toLowerCase().replace(/[^а-яёa-z-]/g,'');
export const isPreposition=word=>PREPOSITIONS.has(bare(word));
export const isTrailingParticle=word=>TRAILING_PARTICLES.has(bare(word));
export const isLeadingParticle=word=>LEADING_PARTICLES.has(bare(word));
export const endsWithPunctuation=word=>/[,.!?:;…]$/.test(word);
export function normalizeText(value,{caps=false}={}){
 let text=String(value??'').replace(/\s+/g,' ').trim();
 text=text.replace(/…/g,'...').replace(/\.{4,}/g,'...').replace(/!\?/g,'?!').replace(/([!?])\1{2,}/g,'$1$1$1');
 text=text.replace(/(^|[\s(])"([^"]+)"/g,'$1«$2»').replace(/“([^”]+)”/g,'«$1»');
 text=text.replace(/ [-–] /g,' — ').replace(/^[-–] /,'— ').replace(/ ([,.!?:;])/g,'$1').replace(/\( /g,'(').replace(/ \)/g,')');
 // A dash never opens a line mid-sentence; lone punctuation never stands on its own line.
 text=text.replace(/(\S) — /g,`$1${NBSP}— `).replace(/ ([.!?…,:;»)]+)(?= |$)/g,`${NBSP}$1`);
 return caps?text.toUpperCase():text;
}
export const splitWords=text=>text.split(' ').filter(Boolean);
