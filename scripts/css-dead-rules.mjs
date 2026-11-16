// Lists CSS selectors that can never match: they need a class that no source
// file (JS/JSX/TS/TSX/HTML in src, index pages, public runtime files) mentions.
// Classes built at runtime from a prefix ('reader-theme-'+theme, `tile-${n}`)
// count as used for every name with that prefix.
//   node scripts/css-dead-rules.mjs src/player.css [more.css…]  [--json] [--write]
// --write drops the dead selectors (and rules/at-rules left empty) in place.
import fs from 'node:fs';
import path from 'node:path';
import postcss from 'postcss';

const ROOT=path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/,'$1')),'..');
const SOURCE=/\.(jsx?|tsx?|html|mjs|py)$/;
function walk(dir,out=[]){
 for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
  const file=path.join(dir,entry.name);
  if(entry.isDirectory()){if(!['node_modules','dist','.git','.codex-local','test-output','tests'].includes(entry.name))walk(file,out);}
  else if(SOURCE.test(entry.name))out.push(file);
 }
 return out;
}
const files=[...walk(path.join(ROOT,'src')),...['lmt','workers','server'].filter(d=>fs.existsSync(path.join(ROOT,d))).flatMap(d=>walk(path.join(ROOT,d))),...fs.readdirSync(ROOT).filter(f=>SOURCE.test(f)).map(f=>path.join(ROOT,f))];
if(fs.existsSync(path.join(ROOT,'public')))files.push(...walk(path.join(ROOT,'public')));
// Third-party components render their own class names.
const vendorPrefixes=['rdp-','stf__','hls-','pdfjs','textLayer','annotationLayer','page-flip'];
const tokens=new Set(),prefixes=new Set(vendorPrefixes);
for(const file of files){
 const text=fs.readFileSync(file,'utf8');
 for(const m of text.matchAll(/[A-Za-z_][\w-]*/g))tokens.add(m[0]);
 for(const m of text.matchAll(/([A-Za-z][\w-]*-)['"`]\s*\+/g))prefixes.add(m[1]);
 for(const m of text.matchAll(/([A-Za-z][\w-]*-)\$\{/g))prefixes.add(m[1]);
}
const used=name=>tokens.has(name)||[...prefixes].some(p=>name.startsWith(p));
const classesOf=selector=>[...selector.replace(/\[[^\]]*\]/g,'').replace(/:not\([^)]*\)/g,'').matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map(m=>m[1]);
// A selector inside :not(), :has(), :where(), :is() is not needed to match; only
// the classes the element chain itself requires make a selector dead.
const deadClass=selector=>classesOf(selector.replace(/:(?:has|where|is)\((?:[^()]|\([^()]*\))*\)/g,'')).find(c=>!used(c));

export function deadSelectors(css,from){
 const out=[];
 postcss.parse(css,{from}).walkRules(rule=>{
  if(rule.parent?.type==='atrule'&&/keyframes/i.test(rule.parent.name))return;
  for(const selector of rule.selectors){const c=deadClass(selector);if(c)out.push({line:rule.source.start.line,selector,class:c,all:rule.selectors.every(s=>deadClass(s))});}
 });
 return out;
}
export function pruneDead(css,from){
 const root=postcss.parse(css,{from});let removed=0;
 root.walkRules(rule=>{
  if(rule.parent?.type==='atrule'&&/keyframes/i.test(rule.parent.name))return;
  const live=rule.selectors.filter(s=>!deadClass(s));
  if(live.length===rule.selectors.length)return;
  removed+=rule.selectors.length-live.length;
  if(!live.length){rule.remove();return;}
  rule.selector=live.join(',');
 });
 let changed=true;while(changed){changed=false;root.walkAtRules(at=>{if(at.nodes&&!at.nodes.length){at.remove();changed=true;}});}
 return {css:root.toString(),removed};
}
export {deadClass,used};

if(process.argv[1]&&path.resolve(process.argv[1])===path.resolve(new URL(import.meta.url).pathname.replace(/^\/(\w:)/,'$1'))){
 const json=process.argv.includes('--json'),write=process.argv.includes('--write');const report={};
 for(const file of process.argv.slice(2).filter(a=>!a.startsWith('--'))){
  const list=deadSelectors(fs.readFileSync(file,'utf8'),file);report[file]=list;
  if(write){const out=pruneDead(fs.readFileSync(file,'utf8'),file);fs.writeFileSync(file,out.css);console.log(file+': removed '+out.removed+' dead selectors');continue;}
  if(!json){console.log(file+': '+list.length+' dead selectors');for(const d of list)console.log('  '+d.line+'  .'+d.class+'  '+d.selector.slice(0,140));}
 }
 if(json)console.log(JSON.stringify(report,null,1));
}
