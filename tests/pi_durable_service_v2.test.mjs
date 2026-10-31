import assert from 'node:assert/strict';
import test from 'node:test';
import { admissionDecision, payloadFingerprint } from '../experiments/pi_durable_service_v2.mjs';

test('a global two-slot budget rejects another session without losing duplicate identity', () => {
  const state = { capacity: 2, active: { 'a:one': 't1', 'b:two': 't2' },
    authority: { a: { allowed: true, version: 1 }, b: { allowed: true, version: 2 } },
    requests: { 'a:one': { taskId: 't1', fingerprint: 'p' } } };
  assert.equal(admissionDecision(state, 'a', 'three', 'q', 1).status, 'overloaded');
  assert.equal(admissionDecision(state, 'b', 'three', 'q', 2).status, 'overloaded');
  assert.deepEqual(admissionDecision(state, 'a', 'one', 'p', 1), { status: 'duplicate', key: 'a:one', taskId: 't1' });
  assert.equal(admissionDecision(state, 'a', 'one', 'p', 99).status, 'unauthorized');
  assert.equal(admissionDecision(state, 'a', 'one', 'changed', 1).status, 'conflict');
  delete state.active['b:two'];
  assert.equal(admissionDecision(state, 'b', 'three', 'q', 2).status, 'admit');
  assert.equal(admissionDecision(state, 'b', 'three', 'q', 1).status, 'unauthorized');
  state.authority.b.allowed = false;
  assert.equal(admissionDecision(state, 'b', 'three', 'q', 2).status, 'unauthorized');
});
test('string request payload identity separates changed bytes and rejects ambiguous objects', () => {
  assert.equal(payloadFingerprint('same'), payloadFingerprint('same'));
  assert.notEqual(payloadFingerprint('same'), payloadFingerprint('same\n'));
  assert.throws(() => payloadFingerprint({ value: 'same' }), TypeError);
});
