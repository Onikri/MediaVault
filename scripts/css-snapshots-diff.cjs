// Compares two css-snapshots captures: element boxes, every computed style
// property, and the screenshots pixel by pixel (tolerance for anti-aliasing).
//   node scripts/css-snapshots-diff.cjs <before-dir> <after-dir> [--examples 6]
// Exit code 1 when anything differs.
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const [A,B]=process.argv.slice(2).filter((a,i,all)=>!a.startsWith('--')&&!['--examples','--ignore'].includes(all[i-1])).map(d=>path.resolve(d));
const examples=Number(process.argv[process.argv.indexOf('--examples')+1])||6;
// --ignore a,b: properties to skip, e.g. custom properties a cleanup removed
// because nothing reads them.
const ignoreAt=process.argv.indexOf('--ignore');
const NOISE=new Set(ignoreAt>0?process.argv[ignoreAt+1].split(','):[]);
const parse=s=>{const m=new Map();if(s==null)return m;for(const part of s.replace(/http:\/\/127\.0\.0\.1:\d+/g,'ORIGIN').split(';')){const i=part.indexOf(':');m.set(part.slice(0,i),part.slice(i+1));}return m;};
let failed=false;
for(const file of fs.readdirSync(A).filter(f=>f.endsWith('.json')).sort()){
 const name=file.replace('.json','');
 if(!fs.existsSync(path.join(B,file))){console.log(name+': missing in after');failed=true;continue;}
 const a=JSON.parse(fs.readFileSync(path.join(A,file))),b=JSON.parse(fs.readFileSync(path.join(B,file)));
 const mb=new Map(b.elements.map(e=>[e[0],e])),ma=new Map(a.elements.map(e=>[e[0],e]));
 const lines=[],byProp=new Map();let boxes=0;
 const missing=[...ma.keys()].filter(k=>!mb.has(k)),extra=[...mb.keys()].filter(k=>!ma.has(k));
 for(const [key,ea] of ma){
  const eb=mb.get(key);if(!eb)continue;
  if(ea[1]!==eb[1]){boxes++;if(boxes<=examples)lines.push('  box '+key.split('>').slice(-3).join('>')+'  '+ea[1]+' → '+eb[1]);}
  if(ea[2]===eb[2]&&a.table[ea[2]]===b.table[eb[2]])continue;
  const sa=parse(a.table[ea[2]]),sb=parse(b.table[eb[2]]);
  for(const p of new Set([...sa.keys(),...sb.keys()])){
   if(NOISE.has(p)||sa.get(p)===sb.get(p))continue;
   const list=byProp.get(p)||[];list.push(key.split('>').slice(-3).join('>')+'  '+sa.get(p)+' → '+sb.get(p));byProp.set(p,list);
  }
 }
 let pixels='';
 const pa=path.join(A,name+'.png'),pb=path.join(B,name+'.png');
 if(fs.existsSync(pa)&&fs.existsSync(pb)){
  pixels=execFileSync('python',['-I','-c',`import sys
from PIL import Image,ImageChops
a=Image.open(sys.argv[1]).convert('RGB');b=Image.open(sys.argv[2]).convert('RGB')
if a.size!=b.size:print('size',a.size,'->',b.size);sys.exit()
d=ImageChops.difference(a,b).convert('L').point(lambda v:255 if v>24 else 0)
n=sum(1 for v in d.getdata() if v);t=a.size[0]*a.size[1]
if n:d.save(sys.argv[3])
print(n,'px',round(100*n/t,3),'%')`,pa,pb,path.join(B,name+'-diff.png')],{encoding:'utf8'}).trim();
 }
 const pixelBad=pixels&&!/^0 px/.test(pixels);
 const clean=!missing.length&&!extra.length&&!boxes&&!byProp.size&&!pixelBad;
 if(clean){console.log(name+': same ('+a.elements.length+' elements, pixels '+pixels+')');continue;}
 failed=true;
 console.log(name+': DIFFERENT  pixels '+pixels+'  missing '+missing.length+'  extra '+extra.length+'  boxes '+boxes+'  props '+byProp.size);
 missing.slice(0,examples).forEach(k=>console.log('  - '+k.split('>').slice(-3).join('>')));
 extra.slice(0,examples).forEach(k=>console.log('  + '+k.split('>').slice(-3).join('>')));
 lines.forEach(l=>console.log(l));
 for(const [p,list] of [...byProp].sort((x,y)=>y[1].length-x[1].length)){console.log('  '+p+' ×'+list.length);list.slice(0,examples).forEach(l=>console.log('    '+l));}
}
process.exitCode=failed?1:0;
