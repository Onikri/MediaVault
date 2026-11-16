// Which !important declarations would win anyway? For each one, every other
// declaration of the same property whose selector could hit the same element
// (shares a class with the subject, or has no class at all) is compared by
// specificity and bundle order. A declaration is "free" when no competitor is
// itself !important and none would beat it without the flag. Inline styles set
// from JS are not visible here: check the component before dropping a flag that
// guards a positioned or sized element.
//   node scripts/css-important-check.mjs <order.txt> src/a.css [more…] [--free]
// order.txt: the main bundle order (one line of name_css tokens, as printed by a
// marker build); files outside it are treated as lazy chunks loaded later.
import fs from 'node:fs';
import path from 'node:path';
import postcss from 'postcss';

const args=process.argv.slice(2),onlyFree=args.includes('--free');
const [orderFile,...targets]=args.filter(a=>!a.startsWith('--'));
const tokens=fs.readFileSync(orderFile,'utf8').split('\n').find(l=>l.startsWith('styles_css')).trim().split(/\s+/);
const nameOf=t=>'src/'+t.replace(/_css$/,'').replace(/^blossom_components_/,'blossom/components/').replace(/^blossom_/,'blossom/').replace(/^control_/,'control/')+'.css';
const order=new Map(tokens.map((t,i)=>[nameOf(t),i]));
const walk=(d,o=[])=>{for(const e of fs.readdirSync(d,{withFileTypes:true})){const f=path.join(d,e.name);if(e.isDirectory())walk(f,o);else if(f.endsWith('.css'))o.push(f.split(path.sep).join('/'));}return o;};
const files=walk('src');
const rank=f=>order.has(f)?order.get(f):1000; // lazy chunks come after main

function specificity(sel){
 let a=0,b=0,c=0;
 sel=sel.replace(/:where\((?:[^()]|\([^()]*\))*\)/g,'');
 sel=sel.replace(/:(?:not|is|has)\(((?:[^()]|\([^()]*\))*)\)/g,(m,inner)=>{const best=inner.split(',').map(s=>specificity(s.trim())).sort((x,y)=>x[0]-y[0]||x[1]-y[1]||x[2]-y[2]).at(-1)||[0,0,0];a+=best[0];b+=best[1];c+=best[2];return '';});
 a+=(sel.match(/#[\w-]+/g)||[]).length;
 b+=(sel.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+(\([^)]*\))?/g)||[]).length;
 c+=(sel.match(/(^|[\s>+~(])[a-zA-Z][\w-]*/g)||[]).length+(sel.match(/::[\w-]+/g)||[]).length;
 return [a,b,c];
}
const cmp=(x,y)=>x[0]-y[0]||x[1]-y[1]||x[2]-y[2];
const subject=sel=>{const s=sel.trim().split(/\s+|>|\+|~/).filter(Boolean).at(-1)||'';const pseudo=(s.match(/::[\w-]+/)||[''])[0];const clean=s.replace(/:not\([^)]*\)/g,'').replace(/::?[\w-]+(\([^)]*\))?/g,'');return {cls:[...clean.matchAll(/\.([\w-]+)/g)].map(m=>m[1]),id:(clean.match(/#([\w-]+)/)||[])[1],tag:(clean.match(/^[a-zA-Z][\w-]*/)||[''])[0].toLowerCase(),pseudo,chain:[...sel.replace(/:not\([^)]*\)/g,'').matchAll(/\.([\w-]+)/g)].map(m=>m[1])};};
// Classes that sit on one element together: every className attribute in the
// components, literal parts and expressions alike.
const together=new Map();
for(const f of walk2('src')){
 const text=fs.readFileSync(f,'utf8');
 for(const m of text.matchAll(/className=(\{(?:[^{}]|\{[^{}]*\})*\}|"[^"]*"|'[^']*')/g)){
  const names=[...new Set([...m[1].matchAll(/[A-Za-z][\w-]*/g)].map(x=>x[0]))];
  for(const a of names){if(!together.has(a))together.set(a,new Set());for(const b of names)together.get(a).add(b);}
 }
}
function walk2(d,o=[]){for(const e of fs.readdirSync(d,{withFileTypes:true})){const f=path.join(d,e.name);if(e.isDirectory())walk2(f,o);else if(/\.(jsx|tsx|js|ts)$/.test(f))o.push(f);}return o;}
const cooccur=(a,b)=>together.get(a)?.has(b);
const family=p=>p.replace(/-(top|right|bottom|left|inline|block|inline-start|inline-end|block-start|block-end|width|style|color|x|y)$/,'');

const decls=[];
for(const f of files){
 postcss.parse(fs.readFileSync(f,'utf8')).walkDecls(d=>{
  const rule=d.parent;if(rule.type!=='rule')return;if(rule.parent?.type==='atrule'&&/keyframes/.test(rule.parent.name))return;
  for(const sel of rule.selectors)decls.push({f,rank:rank(f),line:d.source.start.line,col:d.source.start.column,sel,spec:specificity(sel),sub:subject(sel),prop:d.prop,fam:family(d.prop),important:d.important,media:rule.parent?.type==='atrule'?rule.parent.params:''});
 });
}
const overlap=(x,y)=>{
 if(x.sub.pseudo!==y.sub.pseudo)return false;
 if(x.sub.tag&&y.sub.tag&&x.sub.tag!==y.sub.tag)return false;
 // html and body pass values down by inheritance, not by competing in the cascade.
 if(['html','body'].includes(y.sub.tag)&&x.sub.tag!==y.sub.tag)return false;
 if((x.sub.id&&x.sub.id===y.sub.id)||x.sub.cls.some(c=>y.sub.cls.includes(c)||y.sub.cls.some(d=>cooccur(c,d))))return true;
 if(y.sub.cls.length||y.sub.id){if(x.sub.cls.length||x.sub.id)return false;return false;}
 // y's subject is a bare tag or *: it competes when it is global or shares context.
 return !y.sub.chain.length||y.sub.chain.some(c=>x.sub.chain.includes(c));
};
const later=(x,y)=>y.rank!==x.rank?y.rank>x.rank:y.f!==x.f?null:(y.line-x.line||y.col-x.col)>0;
for(const target of targets.map(t=>t.split(path.sep).join('/'))){
 for(const d of decls.filter(x=>x.f===target&&x.important)){
  const rivals=decls.filter(o=>o!==d&&(o.prop===d.prop||o.fam===d.fam||o.prop===d.fam||d.prop===o.fam)&&overlap(d,o)&&!(o.f===d.f&&o.line===d.line&&o.col===d.col));
  const blockers=[];
  // A bare tag or * subject can carry any class; rules on those classes are not visible here.
  if(!d.sub.cls.length&&!d.sub.id)blockers.push('bare subject: not analysed');
  for(const o of rivals){
   if(o.important){blockers.push('!important '+o.f+':'+o.line+' '+o.sel);continue;}
   const c=cmp(o.spec,d.spec),l=later(d,o);
   if(c>0||(c===0&&l!==false))blockers.push((c>0?'stronger ':l===null?'unknown order ':'later ')+o.f+':'+o.line+' '+(o.media?'@'+o.media+' ':'')+o.sel);
  }
  if(onlyFree&&blockers.length)continue;
  console.log((blockers.length?'KEEP ':'FREE ')+d.f+':'+d.line+' '+d.sel+' { '+d.prop+' }');
  for(const b of blockers.slice(0,4))console.log('     '+b.slice(0,170));
 }
}
