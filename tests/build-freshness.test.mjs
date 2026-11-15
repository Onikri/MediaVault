import test from 'node:test';
import assert from 'node:assert/strict';
import {entryAsset,buildChanged} from '../src/build-freshness.js';

test('a tab is stale only when the published entry differs from the loaded one',()=>{
 const page=name=>'<script type="module" crossorigin src="./assets/'+name+'"></script>';
 assert.equal(entryAsset('https://example.org/app/assets/main-Uf5hm_is.js'),'assets/main-Uf5hm_is.js');
 assert.equal(buildChanged('https://example.org/app/assets/main-Uf5hm_is.js',page('main-Uf5hm_is.js')),false);
 assert.equal(buildChanged('https://example.org/app/assets/main-OLD00000.js',page('main-Uf5hm_is.js')),true);
 assert.equal(buildChanged('http://127.0.0.1:5173/src/main.jsx',page('main-Uf5hm_is.js')),false,'dev server has no hashed entry');
 assert.equal(buildChanged('https://example.org/app/assets/main-Uf5hm_is.js','<html>error page</html>'),false);
});
