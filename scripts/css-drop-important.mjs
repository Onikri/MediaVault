// Drops the !important flag from chosen declarations: file:line:property, where
// line is the declaration's line (as css-important-check.mjs prints the rule).
// Every selector of that rule must have been reported FREE.
//   node scripts/css-drop-important.mjs src/a.css:12:border src/a.css:12:border-radius
import fs from 'node:fs';
import postcss from 'postcss';

const byFile=new Map();
for(const spec of process.argv.slice(2)){const [file,line,prop]=spec.split(':');if(!byFile.has(file))byFile.set(file,[]);byFile.get(file).push({line:Number(line),prop});}
for(const [file,list] of byFile){
 const root=postcss.parse(fs.readFileSync(file,'utf8'));let n=0;
 root.walkDecls(d=>{if(d.important&&list.some(x=>x.line===d.source.start.line&&x.prop===d.prop)){d.important=false;d.raws.important=undefined;n++;}});
 fs.writeFileSync(file,root.toString());
 console.log(file,n+'/'+list.length);
}
