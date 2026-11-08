// Adds or updates Ukrainian translations: node scripts/i18n-add.mjs <file.json with {"ru":"uk"}>
import fs from 'node:fs';
const target=new URL('../src/i18n/uk.json',import.meta.url);
const dictionary=JSON.parse(fs.readFileSync(target,'utf8'));
const additions=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
Object.assign(dictionary,additions);
const sorted=Object.fromEntries(Object.entries(dictionary).sort(([a],[b])=>a.localeCompare(b,'ru')));
fs.writeFileSync(target,JSON.stringify(sorted,null,0).replaceAll('","','",\n"')+'\n');
console.log('Ukrainian dictionary: '+Object.keys(sorted).length+' entries (+'+Object.keys(additions).length+').');
