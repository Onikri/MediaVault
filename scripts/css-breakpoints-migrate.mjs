// Rewrites raw width queries to the named breakpoints (src/blossom/breakpoints.css).
// Only unambiguous ranges are rewritten; anything else is reported for a person.
//   node scripts/css-breakpoints-migrate.mjs src/a.css [more…] [--write]
// max-width 420–767 → --phone, 768–1279 → --tablet; min-width 641–768 → --above-phone,
// 769–1279 → --desktop; (--above-phone) and (--tablet) → --tablet-only. At the
// snapshot widths (320/390/768/1280/1440) every rewrite matches the old query,
// in between the old and new widths a layout switches a little earlier or later.
import fs from 'node:fs';

const write=process.argv.includes('--write');
const map=(kind,n)=>kind==='max'?(n>=420&&n<=767?'(--phone)':n>=768&&n<=1279?'(--tablet)':null):(n>=641&&n<=768?'(--above-phone)':n>=769&&n<=1279?'(--desktop)':null);
for(const file of process.argv.slice(2).filter(a=>!a.startsWith('--'))){
 const text=fs.readFileSync(file,'utf8');const manual=[],changed=[];
 const out=text.replace(/@media\s*([^{]*?)\s*\{/g,(whole,params)=>{
  if(!/(min|max)-width/.test(params))return whole;
  let bad=false;
  let next=params.replace(/\(\s*(min|max)-width\s*:\s*(\d+)px\s*\)/g,(m,kind,n)=>{const t=map(kind,Number(n));if(!t)bad=true;return t||m;});
  next=next.replace(/\(--above-phone\)\s+and\s+\(--tablet\)|\(--tablet\)\s+and\s+\(--above-phone\)/g,'(--tablet-only)');
  // A range squeezed between two old widths has no three-breakpoint equivalent.
  if(/\(--(desktop|above-phone)\)/.test(next)&&/\(--(tablet|phone)\)/.test(next))bad=true;
  if(bad||/(min|max)-width/.test(next)){manual.push(params);return whole;}
  changed.push(params+' → '+next);
  return '@media '+next+'{';
 });
 console.log(file+': '+changed.length+' rewritten'+(manual.length?', manual: '+manual.join(' | '):''));
 if(write)fs.writeFileSync(file,out);
}
