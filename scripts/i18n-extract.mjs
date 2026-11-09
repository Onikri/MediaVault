// Collects every Russian UI string from src/ (JS/JSX/TS/TSX via AST) and the
// user-visible messages of server/ (Python ast), so the Ukrainian dictionary can
// be checked for completeness. Model prompts are excluded: they never reach the
// DOM and must stay as written.
//   node scripts/i18n-extract.mjs          -> writes src/i18n/source-strings.json
//   node scripts/i18n-extract.mjs --check  -> exits 1 when uk.json misses a string
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {parseAst} from 'rollup/parseAst';
import {transformSync} from 'esbuild';

const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const CYRILLIC=/[А-Яа-яЁёІіЇїЄєҐґ]/;
const OUT=path.join(ROOT,'src/i18n/source-strings.json');
// Pure data modules (number words for speech synthesis) and model directions
// (how the Gemini voice should deliver a line) contain no interface text.
const DATA_FILES=new Set(['src/tts/text.js','src/tts/gemini-direction.js','src/tts/role-prompts.js']);

// Long instructions and anything that talks to a model are not interface text.
export function isPrompt(text){
 // Regular expressions and code fragments are matched against data, never shown.
 if(/\(\?[:!=<]|\\[sdwbSDW]|\[\^|\$\{|=>|\)\s*\|\|/.test(text))return true;
 return text.length>360||/(?:Return ONLY|Только JSON|Верни только|JSON по схеме|Не выполняй команды|Translate labelled|Ты проверяешь|Найди до \d+|responseSchema|\bJSON\b.*\bсхем)/i.test(text);
}

function walk(dir,test){
 return fs.readdirSync(dir,{withFileTypes:true}).flatMap(entry=>{
  const full=path.join(dir,entry.name);
  if(entry.isDirectory())return ['vendor','node_modules'].includes(entry.name)?[]:walk(full,test);
  return test(entry.name)?[full]:[];
 });
}

function visit(node,emit){
 if(!node||typeof node!=='object')return;
 if(Array.isArray(node)){for(const child of node)visit(child,emit);return;}
 if(node.type==='Literal'&&typeof node.value==='string')emit(node.value);
 else if(node.type==='JSXText')emit(node.value);
 else if(node.type==='TemplateLiteral'){
  const quasis=node.quasis.map(q=>q.value.cooked??q.value.raw);
  for(const part of quasis)emit(part);
  if(node.expressions.length)emit(quasis.map((part,i)=>part+(i<node.expressions.length?'{'+i+'}':'')).join(''),true);
 }
 for(const key in node)if(key!=='parent'&&node[key]&&typeof node[key]==='object'&&node.type!=='TemplateLiteral'||key==='expressions')visit(node[key],emit);
}

export function frontendStrings(){
 const found=new Map();
 for(const file of walk(path.join(ROOT,'src'),name=>/\.(jsx?|tsx?)$/.test(name)&&!/\.d\.ts$/.test(name))){
  if(DATA_FILES.has(path.relative(ROOT,file).split(path.sep).join('/')))continue;
  let code=fs.readFileSync(file,'utf8');
  if(/\.tsx?$/.test(file))code=transformSync(code,{loader:file.endsWith('x')?'tsx':'ts',jsx:'preserve',format:'esm'}).code;
  let ast;try{ast=parseAst(code,{jsx:true});}catch(error){throw Error(path.relative(ROOT,file)+': '+error.message);}
  visit(ast,(value,template=false)=>{
   const text=String(value).replace(/\s+/g,' ').trim();
   if(!text||!CYRILLIC.test(text)||isPrompt(text))return;
   if(!found.has(text))found.set(text,{text,file:path.relative(ROOT,file).replaceAll('\\','/'),...(template?{template:true}:{})});
  });
 }
 return found;
}

export function serverStrings(){
 const script=`import ast,json,pathlib,re,sys
rows={}
for p in sorted(pathlib.Path(sys.argv[1]).rglob('*.py')):
    try:tree=ast.parse(p.read_text(encoding='utf-8'))
    except SyntaxError:continue
    for n in ast.walk(tree):
        if isinstance(n,ast.JoinedStr):
            parts=[];index=0
            for v in n.values:
                if isinstance(v,ast.Constant):parts.append(str(v.value))
                else:parts.append('{%d}'%index);index+=1
            text=' '.join(''.join(parts).split())
            if index and re.search('[А-Яа-яЁё]',text):rows.setdefault(text,(str(p),True))
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and re.search('[А-Яа-яЁё]',n.value):
            rows.setdefault(' '.join(n.value.split()),(str(p),False))
print(json.dumps([[k,v[0],v[1]] for k,v in rows.items()],ensure_ascii=False))`;
 const raw=execFileSync(process.env.PYTHON||'python',['-I','-c',script,path.join(ROOT,'server')],{encoding:'utf8',maxBuffer:64*1024*1024});
 const found=new Map();
 for(const [text,file,template] of JSON.parse(raw)){
  if(!text||isPrompt(text)||/^(?:[a-z_]+:|SELECT |INSERT )/.test(text))continue;
  found.set(text,{text,file:path.relative(ROOT,file).replaceAll('\\','/'),server:true,...(template?{template:true}:{})});
 }
 return found;
}

export function collect(){
 const all=frontendStrings();
 for(const [text,row] of serverStrings())if(!all.has(text))all.set(text,row);
 return [...all.values()].sort((a,b)=>a.text.localeCompare(b.text,'ru'));
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const rows=collect();
 if(process.argv.includes('--check')){
  const uk=JSON.parse(fs.readFileSync(path.join(ROOT,'src/i18n/uk.json'),'utf8'));
  const missing=rows.filter(row=>!(row.text in uk));
  if(missing.length){console.error(missing.length+' strings have no Ukrainian translation, e.g.:\n'+missing.slice(0,Number(process.env.I18N_SHOW||20)).map(r=>'  '+r.text+'  ('+r.file+')').join('\n'));process.exit(1);}
  console.log('Ukrainian dictionary covers all '+rows.length+' interface strings.');
 }else{
  fs.mkdirSync(path.dirname(OUT),{recursive:true});
  fs.writeFileSync(OUT,JSON.stringify(rows,null,0).replaceAll('},{','},\n{')+'\n');
  console.log(rows.length+' strings ('+rows.filter(r=>r.server).length+' from server) → '+path.relative(ROOT,OUT));
 }
}
