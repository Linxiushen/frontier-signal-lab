import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateSubmissionIdentity, reservationAction, effectDecision } from '../experiments/pi_generation_admission_service.mjs';
import { payloadFingerprint } from '../experiments/pi_durable_service_v2.mjs';
const request = { conversation: 'c', requestId: 'r', payload: 'p', version: 3, fingerprint: payloadFingerprint('p') };
const native = { id: 'n', type: 'input', conversationId: 'c', requestId: 'r' };
const entry = { kind: 'pi.user', conversationId: 'c', model: [{ role: 'user', content: JSON.stringify({ key: 'c:r', payload: 'p', version: 3 }) }] };
test('recover the exact original submission identity and content', () => {
  validateSubmissionIdentity(request, native, entry);
  for (const change of [{ type: 'write' }, { conversationId: 'other' }, { requestId: 'other' }])
    assert.throws(() => validateSubmissionIdentity(request, { ...native, ...change }, entry), /mismatch/);
});
test('same request ID cannot import changed payload or argument version', () => {
  for (const content of ['changed', JSON.stringify({ key: 'c:r', payload: 'q', version: 3 }), JSON.stringify({ key: 'c:r', payload: 'p', version: 4 })])
    assert.throws(() => validateSubmissionIdentity(request, native, { ...entry, model: [{ role: 'user', content }] }), /mismatch/);
  for (const changed of [undefined, { ...entry, kind: 'other' }, { ...entry, conversationId: 'other' }, { ...entry, model: [] }])
    assert.throws(() => validateSubmissionIdentity(request, native, changed), /mismatch/);
});
test('pending reservation rechecks current permission and durable cancellation', () => {
  const state = { authority: { c: { allowed: true, version: 3 } } };
  assert.equal(reservationAction(state, request), 'submit');
  state.authority.c.version = 4; assert.equal(reservationAction(state, request), 'denied-before-submit');
  state.authority.c = { allowed: false, version: 3 }; assert.equal(reservationAction(state, request), 'denied-before-submit');
  assert.equal(reservationAction({ authority: {} }, request), 'denied-before-submit');
  assert.equal(reservationAction(state, { ...request, cancelled: true }), 'cancelled-before-submit');
});
test('cancel mark survives signal loss and blocks even an existing local effect replay', () => {
  const state = { authority: { c: { allowed: true, version: 3 } }, requests: { 'c:r': { ...request, cancelled: true } }, effects: { 'c:r': { count: 1, payload: 'p' } } };
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'aborted');
  state.requests['c:r'].cancelled = false;
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'existing');
  state.authority.c.allowed = false;
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'denied');
});
