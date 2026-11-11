import test from 'node:test';import assert from 'node:assert/strict';
import {portableConfig} from '../src/lmt-client.js';

test('reader callbacks never reach the LMT MessagePort', () => {
  const onRecovered = index => index + 1;
  const config = {target: 'ru', onRecovered, nested: {keep: 1, drop() {}}, list: [1, () => 2], blob: new Uint8Array([1])};
  const sent = portableConfig(config);
  assert.equal('onRecovered' in sent, false);
  assert.deepEqual(sent.nested, {keep: 1});
  assert.deepEqual(sent.list, [1, undefined]);
  assert.ok(sent.blob instanceof Uint8Array);
  assert.doesNotThrow(() => structuredClone(sent));
  assert.throws(() => structuredClone(config), /could not be cloned/);
  assert.equal(config.onRecovered, onRecovered);
});
