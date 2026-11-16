// Every rule in src/**/*.css whose selector subject (its last compound) has all
// the given classes, with the declarations of the given properties. Used to see
// what an !important actually competes with before removing it.
//   node scripts/css-rules-for.mjs .mv-player,.is-sheet position width border
import fs from 'node:fs';
import path from 'node:path';
import postcss from 'postcss';

const [tokens,...props]=process.argv.slice(2);
const need=tokens.split(',');
function walk(dir,out=[]){
 for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
  const file=path.join(dir,entry.name);
  if(entry.isDirectory())walk(file,out);else if(file.endsWith('.css'))out.push(file);
 }
 return out;
}
const hasClass=(compound,token)=>new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?![\\w-])').test(compound);
for(const file of walk('src')){
 postcss.parse(fs.readFileSync(file,'utf8')).walkRules(rule=>{
  if(rule.parent?.type==='atrule'&&/keyframes/.test(rule.parent.name))return;
  for(const selector of rule.selectors){
   const subject=selector.trim().replace(/::?[\w-]+(\([^)]*\))?/g,m=>m.startsWith(':not')?m:'').split(/\s+|>|\+|~/).filter(Boolean).at(-1)||'';
   if(!need.every(t=>hasClass(subject,t)))continue;
   const decls=[];
   rule.walkDecls(d=>{if(!props.length||props.some(p=>d.prop===p||d.prop.startsWith(p+'-')))decls.push(d.prop+':'+d.value+(d.important?' !important':''));});
   if(!decls.length)continue;
   const media=rule.parent?.type==='atrule'?'@'+rule.parent.params+' ':'';
   console.log(file.split(path.sep).join('/')+':'+rule.source.start.line+'  '+media+selector+'  {'+decls.join('; ').slice(0,240)+'}');
  }
 });
}
