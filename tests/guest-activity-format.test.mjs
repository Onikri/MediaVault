import test from 'node:test';
import assert from 'node:assert/strict';
import {bytes,device,duration,EVENT_GROUPS} from '../src/guest-activity-format.js';

test('activity formatting reads like the owner expects',()=>{
 assert.equal(bytes(0),'0 Б');
 assert.equal(bytes(4140000),'3.95 МБ');
 assert.equal(bytes(5*1024**3),'5 ГБ');
 assert.equal(device('Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36'),'Chrome · Android');
 assert.equal(device('Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Version/18.1 Mobile/15E148 Safari/604.1'),'Safari · iPhone');
 assert.equal(device(''),'Неизвестное устройство');
 assert.equal(duration(30),'меньше минуты');
 assert.equal(duration(3725),'1 ч 2 мин');
 const watch=EVENT_GROUPS.find(g=>g[0]==='watch')[2],sign=EVENT_GROUPS.find(g=>g[0]==='sign')[2];
 assert.ok(watch('Запустил просмотр')&&!watch('Неверный пароль'));
 assert.ok(sign('Неверный пароль')&&sign('Вошёл в профиль'));
});
