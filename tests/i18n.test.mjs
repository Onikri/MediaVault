import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createTranslator,PHRASE_LIMIT} from '../src/i18n/translate.js';

const dictionary=JSON.parse(fs.readFileSync(new URL('../src/i18n/uk.json',import.meta.url),'utf8'));
const translate=createTranslator(dictionary);

test('exact interface strings are translated and whitespace is preserved',()=>{
 assert.equal(translate('Настройки плеера'),'Налаштування плеєра');
 assert.equal(translate('  Настройки плеера\n'),'  Налаштування плеєра\n');
 assert.equal(translate('Latin only'),'Latin only');
});

test('numbers inside known templates are kept',()=>{
 assert.equal(translate('Серия 12'),'Серія 12');
 assert.equal(translate('Готово: сохранено 3, уже были в Drive 1, недоступны 0.'),'Готово: збережено 3, уже були в Drive 1, недоступні 0.');
 assert.equal(translate('Google временно занят · повтор через 17 с'),'Google тимчасово зайнятий · повтор через 17 с');
});

test('composed short strings translate their known phrases only',()=>{
 assert.equal(translate('Аня, играет'),'Аня, грає');
 assert.equal(translate('12 серий'),'12 серій');
 assert.equal(translate('Вышло 5 / 12 сер.'),'Вийшло 5 / 12 сер.');
});

test('lowercase and capitalised variants of a phrase are both found',()=>{
 const small=createTranslator({'Открыть плеер':'Відкрити плеєр'});
 assert.equal(small('открыть плеер сейчас'),'відкрити плеєр сейчас');
 assert.equal(small('Открыть плеер'),'Відкрити плеєр');
});

test('long content without an exact entry is left untouched',()=>{
 const prose='Серия '.repeat(Math.ceil(PHRASE_LIMIT/6)+5);
 assert.equal(translate(prose),prose);
});

test('phrases never match inside a longer word',()=>{
 const small=createTranslator({'Серия':'Серія'});
 assert.equal(small('Серияльный'),'Серияльный');
});

test('every placeholder survives translation',()=>{
 for(const [source,target] of Object.entries(dictionary)){
  const marks=value=>(value.match(/\{\d+\}/g)||[]).sort().join();
  assert.equal(marks(target),marks(source),source);
 }
});
