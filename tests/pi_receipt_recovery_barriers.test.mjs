import test from 'node:test';
import assert from 'node:assert/strict';
import { createRecoveryClient } from '../experiments/pi_receipt_recovery_barriers.mjs';

function held() {
  const pending = new Map();
  return { hold: label => new Promise(resolve => { assert.ok(!pending.has(label)); pending.set(label, resolve); }),
    release: label => { assert.ok(pending.has(label)); pending.get(label)(); pending.delete(label); },
    pending };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('late missing holds the actual second read and performs only the first apply', async () => {
  const gate = held(), calls = [], receipt = { durable: 'transport-result' };
  const client = createRecoveryClient({ key: 'target', mode: 'late-missing', hold: gate.hold,
    client: { lookup: async id => { calls.push(['GET', id.key]); return undefined; },
      apply: async id => { calls.push(['POST', id.key]); return receipt; } } });
  const id = { key: 'target' };
  assert.equal(await client.lookup(id), undefined);
  const first = client.apply(id), second = client.lookup(id); await tick();
  assert.deepEqual(calls, [['GET', 'target'], ['GET', 'target']]);
  gate.release('first-apply'); assert.equal(await first, receipt);
  gate.release('late-missing'); assert.equal(await second, undefined);
  assert.deepEqual(calls, [['GET', 'target'], ['GET', 'target'], ['POST', 'target']]);
  await assert.rejects(client.lookup(id), /Exactly two/);
});

test('late refusal is obtained from transport before first apply and delivered afterward', async () => {
  const gate = held(), calls = [], receipt = { receipt: { count: 1 }, created: true }, refusal = { denied: true };
  let allowed = false;
  const client = createRecoveryClient({ key: 'target', mode: 'late-refusal', hold: gate.hold,
    client: { lookup: async () => undefined,
      apply: async () => { calls.push(allowed ? 'created' : 'denied'); return allowed ? receipt : refusal; } } });
  const id = { key: 'target' };
  await client.lookup(id); const first = client.apply(id); await client.lookup(id);
  const second = client.apply(id); await tick();
  assert.deepEqual(calls, ['denied']); assert.ok(gate.pending.has('late-refusal'));
  allowed = true; gate.release('first-apply'); assert.equal(await first, receipt);
  allowed = false; gate.release('late-refusal'); assert.equal(await second, refusal);
  assert.deepEqual(calls, ['denied', 'created']);
});

test('unrelated identities pass through unchanged and unexpected responses fail closed', async () => {
  const receipt = { exact: true }, calls = [];
  const client = createRecoveryClient({ key: 'target', mode: 'late-missing',
    hold: async () => { throw new Error('Unexpected hold'); },
    client: { lookup: async id => { calls.push(id); return receipt; }, apply: async () => receipt } });
  const other = { key: 'other' };
  assert.equal(await client.lookup(other), receipt); assert.equal(await client.apply(other), receipt);
  assert.deepEqual(calls, [other]);
  await assert.rejects(client.lookup({ key: 'target' }), /actual missing transport response/);
});
