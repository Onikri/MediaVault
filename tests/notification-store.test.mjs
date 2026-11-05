import test from 'node:test';
import assert from 'node:assert/strict';
import {notificationStore} from '../src/notification-store.js';
test('notifications group repeats, mark read, remain account scoped and retain task navigation',()=>{
 const a=notificationStore('contract-A'),b=notificationStore('contract-B');a.clear();b.clear();
 a.push({id:'first',message:'Глава готова',taskId:'job-1'});a.push({id:'second',message:'Глава готова',taskId:'job-1'});
 assert.equal(a.getSnapshot().length,1);assert.equal(a.getSnapshot()[0].count,2);assert.equal(a.getSnapshot()[0].taskId,'job-1');assert.equal(b.getSnapshot().length,0);
 a.read();assert.equal(a.getSnapshot()[0].read,true);a.push({id:'third',message:'Нужен доступ',bad:true});assert.equal(a.getSnapshot().filter(v=>!v.read).length,1);
 for(let i=0;i<110;i++)a.push({id:'more-'+i,message:'Глава '+i});assert.equal(a.getSnapshot().length,100);assert.equal(a.getSnapshot()[0].id,'more-109');a.clear();
});
