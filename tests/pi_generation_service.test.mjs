import { test } from 'node:test';
import assert from 'node:assert/strict';
import { effectDecision } from '../experiments/pi_generation_service.mjs';
import { payloadFingerprint } from '../experiments/pi_durable_service_v2.mjs';
const make = () => ({ authority: { c: { version: 3, allowed: true } }, effects: {},
  requests: { k: { conversation: 'c', payload: 'p', version: 3, fingerprint: payloadFingerprint('p') } } });
const args = { key: 'k', payload: 'p', version: 3 };
test('tool effect validates durable identity and current authority', () => {
  const s = make(); assert.equal(effectDecision(s, args, 'c', false), 'commit');
  s.authority.c.version++; assert.equal(effectDecision(s, args, 'c', false), 'denied');
  s.authority.c.version = 3; s.authority.c.allowed = false;
  assert.equal(effectDecision(s, args, 'c', false), 'denied');
});
test('model arguments cannot redirect an effect or change the payload', () => {
  for (const [change, conversation] of [[{ key: 'unknown' }, 'c'], [{ payload: 'q' }, 'c'], [{ version: 4 }, 'c'], [{}, 'other']])
    assert.equal(effectDecision(make(), { ...args, ...change }, conversation, false), 'conflict');
});
test('pre-effect cancellation and replay use distinct decisions', () => {
  const s = make(); assert.equal(effectDecision(s, args, 'c', true), 'aborted');
  s.effects.k = { count: 1, payload: 'p' }; assert.equal(effectDecision(s, args, 'c', false), 'existing');
  s.authority.c.allowed = false; assert.equal(effectDecision(s, args, 'c', false), 'denied');
});
