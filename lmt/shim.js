// SPDX-License-Identifier: AGPL-3.0-or-later
const prefix='mv_lmt:';
globalThis.storage={async getItem(key){try{return JSON.parse(localStorage.getItem(prefix+key)||'null');}catch{return null;}},async setItem(key,value){localStorage.setItem(prefix+key,JSON.stringify(value));},async getItems(keys){return Promise.all(keys.map(async key=>({key,value:await this.getItem(key)})));}};
globalThis.browser={runtime:{getURL:path=>new URL(String(path).replace(/^\//,''),new URL('./',location.href)).href,sendMessage:async()=>{throw Error('Extension-only action is unavailable in the standalone web engine');}}};
