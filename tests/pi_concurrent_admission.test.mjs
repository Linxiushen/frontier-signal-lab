// Caller controls only. No optional Pi runtime, native process, HTTP or model opens.
import assert from 'node:assert/strict';
import test from 'node:test';
import { createConcurrentAdmissionRound } from '../experiments/pi_concurrent_admission.mjs';

const requests = () => [1, 2].map(conversation => ({ conversation, requestId: 'request',
  key: `${conversation}:request`, payload: `p${conversation}`, version: 1 }));

function serviceFor(round, events, transform = value => value) {
  const entries = new Map();
  let calls = 0;
  return { async admit(conversation, requestId) {
    const key = `${conversation}:${requestId}`;
    calls++;
    await round.gate('before-reserve', key);
    assert.equal(calls, 3, 'Caller must offer all three before allowing any reservation');
    assert.equal(events.filter(e => e.type === 'concurrent-reserve-release').length, 1);
    const existing = entries.get(key);
    if (!existing) entries.set(key, entries.size + 1);
    return transform({ status: existing ? 'duplicate' : 'admit', key, submissionId: entries.get(key) });
  } };
}

test('three overlapping public calls preserve one original identity for exact retry', async () => {
  const events = [], round = createConcurrentAdmissionRound({ emit: e => events.push(e) });
  const result = await round.run(serviceFor(round, events), requests(), 'finite-round');
  assert.deepEqual(result, [{ status: 'admit', key: '1:request', submissionId: 1 },
    { status: 'admit', key: '2:request', submissionId: 2 }]);
  assert.deepEqual(events.map(e => e.type), ['concurrent-admission-open', 'concurrent-reserve-arrival',
    'concurrent-reserve-arrival', 'concurrent-reserve-arrival', 'concurrent-reserve-release', 'concurrent-admission-close']);
  assert.equal(events.at(-1).results[2].status, 'duplicate');
});

test('a duplicate native binding that forks the submission is refused', async () => {
  const events = [], round = createConcurrentAdmissionRound({ emit: e => events.push(e) });
  const service = serviceFor(round, events, r => r.status === 'duplicate' ? { ...r, submissionId: 99 } : r);
  await assert.rejects(round.run(service, requests(), 'forked'), /original submission/);
  assert.equal(events.some(e => e.type === 'concurrent-admission-close'), false);
});

test('a service that performs two admissions for the same request is refused', async () => {
  const events = [], round = createConcurrentAdmissionRound({ emit: e => events.push(e) });
  await assert.rejects(round.run(serviceFor(round, events, r => ({ ...r, status: 'admit' })), requests(), 'double'));
});

test('foreign request identity cannot masquerade as an exact retry', async () => {
  const events = [], round = createConcurrentAdmissionRound({ emit: e => events.push(e) });
  await assert.rejects(round.run(serviceFor(round, events, r => ({ ...r, key: 'foreign' })), requests(), 'foreign'));
});

test('missing real reservation arrival expires and permits a separately named caller round', async () => {
  const events = [], round = createConcurrentAdmissionRound({ timeoutMs: 10, emit: e => events.push(e) });
  let calls = 0;
  const missing = { async admit(conversation, requestId) {
    if (++calls === 3) throw new Error('entry failed');
    await round.gate('before-reserve', `${conversation}:${requestId}`);
    return {};
  } };
  await assert.rejects(round.run(missing, requests(), 'missing'), /barrier deadline/);
  events.splice(0);
  await round.run(serviceFor(round, events), requests(), 'independent-control');
});

test('another active caller round and malformed duplicate conversations are refused', async () => {
  const events = [], round = createConcurrentAdmissionRound({ emit: e => events.push(e) });
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const inner = serviceFor(round, events);
  const service = { async admit(...args) { await held; return inner.admit(...args); } };
  const pending = round.run(service, requests(), 'first');
  await assert.rejects(round.run(service, requests(), 'second'), /One finite/);
  release(); await pending;
  const same = requests(); same[1].conversation = same[0].conversation;
  await assert.rejects(round.run(service, same, 'same-conversation'));
});

test('only declared before-reserve calls participate in the admission barrier', async () => {
  const round = createConcurrentAdmissionRound();
  await round.gate('after-reserve', 'not-a-round');
  await round.gate('before-reserve', 'outside');
  assert.throws(() => createConcurrentAdmissionRound({ timeoutMs: 8001 }));
});
