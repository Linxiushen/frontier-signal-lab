// Fixed time-paced load on two independent Harness/Session+SQLite instances.
import assert from 'node:assert/strict';
import { readFileSync, renameSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { openService, runtimeUrls } from '../experiments/pi_durable_service_v2.mjs';
import { BoundedRetryQueue } from '../experiments/pi_bounded_retry.mjs';

const [runtimeDir, outputDir, stageText, mode] = process.argv.slice(2);
const stage = Number(stageText), output = resolve(outputDir), started = performance.now();
assert.ok([0, 1, 2].includes(stage)); assert.ok(['refuse', 'retry'].includes(mode));
const events = [], gates = new Set(), services = [], releaseAt = new Map(), postCancelled = new Set();
let callbackMs = 0, callbackBytes = 0;
const emit = value => {
  const at = performance.now();
  const line = JSON.stringify({ pid: process.pid, stage, at_epoch_ms: Date.now(), monotonic_ms: at, ...value }) + '\n';
  events.push(line); callbackBytes += Buffer.byteLength(line); callbackMs += performance.now() - at;
};
globalThis.fetch = async () => { emit({ type: 'network-access-denied' }); throw new Error('No provider/network access'); };
const save = (name, value) => {
  const path = resolve(output, name), temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, JSON.stringify(value, null, 2)); renameSync(temporary, path);
};
const wait = async predicate => {
  const end = performance.now() + 8000;
  while (!await predicate()) { assert.ok(performance.now() < end, 'Frozen8s condition deadline'); await delay(2); }
};
const release = (service, phase, key) => gates.add(`${service}:${phase}:${key}`);
let ids = stage === 0 ? { conversations: [[], []], requests: [], terminals: {}, recover: [] } :
  JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8'));
for (let s = 0; s < 2; s++) {
  const phaseGate = async (phase, key, signal) => {
    while (!gates.has(`${s}:${phase}:${key}`)) {
      if (signal.aborted) throw signal.reason ?? new Error('cancelled');
      await delay(2, undefined, { signal });
    }
  };
  const service = await openService({ ...runtimeUrls(runtimeDir), database: resolve(output, `service${s}.sqlite`),
    capacity: 2, phaseGate, emit: e => emit({ service: s, ...e }) });
  services.push(service);
  assert.equal((await service.harness.inspect(service.context)).scheduling, 'paused');
  if (stage === 0) {
    for (let c = 0; c < 2; c++) ids.conversations[s].push(await service.createSession());
  }
  for (const conversation of ids.conversations[s]) await service.authorize(conversation, stage + 1, true);
}
const task = async r => services[r.service].harness.getTask(r.taskId, services[r.service].context);
const observeTerminals = async () => {
  for (const r of ids.requests.filter(r => r.taskId && !ids.terminals[`${r.service}:${r.taskId}`])) {
    const record = await task(r);
    if (record.state.status === 'terminal') {
      const terminal = { outcome: record.state.outcome, at_epoch_ms: Date.now() };
      ids.terminals[`${r.service}:${r.taskId}`] = terminal;
      emit({ type: 'observed-terminal', service: r.service, id: r.id, key: r.key, taskId: r.taskId, ...terminal });
    }
  }
};
if (stage > 0) {
  const recovered = ids.requests.filter(r => r.taskId && !ids.terminals[`${r.service}:${r.taskId}`]);
  assert.equal(recovered.length, 2);
  for (const r of recovered) {
    const record = await task(r);
    assert.equal(record.state.status, 'pending'); assert.equal(record.state.checkpoint.phase, 'finish');
    emit({ type: 'recovered-finish', service: r.service, id: r.id, key: r.key, taskId: r.taskId, recovered_state: record.state });
    release(r.service, 'finish', r.key); ids.recover.push({ stage, service: r.service, id: r.id, taskId: r.taskId });
  }
  for (const service of services) service.harness.resume();
  await wait(async () => { await observeTerminals(); return recovered.every(r => ids.terminals[`${r.service}:${r.taskId}`]); });
}
async function admit(r) {
  const result = await services[r.service].admit(ids.conversations[r.service][r.conversation], r.id, r.payload, stage + 1, r.hold);
  if (result.status === 'admit') Object.assign(r, result);
  return result;
}
const controls = [];
for (let s = 0; s < 2; s++) {
  for (let c = 0; c < 2; c++) {
    const intent = stage === 0 ? (c === 0 ? 'recover' : 'deny') :
      stage === 1 ? (c === 0 ? 'pre-abort' : 'post-abort') : 'commit';
    const r = { id: `s${stage}-db${s}-control${c}`, service: s, conversation: c, stage, kind: 'control',
      intent, hold: intent !== 'commit', payload: `payload-s${stage}-db${s}-control${c}`, at_epoch_ms: Date.now() };
    assert.equal((await admit(r)).status, 'admit'); ids.requests.push(r); controls.push(r);
  }
}
for (const service of services) service.harness.resume();
const epoch = performance.now();
const queue = new BoundedRetryQueue({ retry: mode === 'retry', clock: () => performance.now(), emit,
  admit, capacity: 4, maxAttempts: 8, intervalMs: 20, deadlineMs: 200 });
let offered = 0, controlsReleased = false;
const releaseControls = async () => {
  for (const r of controls) {
    if (r.intent === 'deny') await services[r.service].authorize(ids.conversations[r.service][1], 99, false);
    if (r.intent === 'pre-abort') await services[r.service].cancel(r.taskId);
    else release(r.service, 'effect', r.key);
  }
  controlsReleased = true;
};
while (offered < 12 || queue.pending.length) {
  const elapsed = performance.now() - epoch;
  // Fixed schedule does not wait for task completion. Lateness is retained.
  while (offered < 12 && elapsed >= offered * 10) {
    const s = offered % 2;
    const r = { id: `s${stage}-load${offered}`, service: s, conversation: 0, stage, kind: 'load',
      intent: 'commit', hold: false, payload: `payload-s${stage}-load${offered}`,
      at_epoch_ms: Date.now(), scheduled_ms: offered * 10, offered_ms: performance.now() - epoch };
    ids.requests.push(r); emit({ type: 'offered', ...r });
    await queue.offer(r);
    if (r.taskId) releaseAt.set(r.id, { request: r, at: performance.now() + 40 });
    offered++;
  }
  if (!controlsReleased && performance.now() - epoch >= 120) {
    await releaseControls();
  }
  await queue.tick();
  for (const entry of queue.finished) {
    const r = entry.request;
    if (r.taskId && !releaseAt.has(r.id)) releaseAt.set(r.id, { request: r, at: performance.now() + 40 });
  }
  for (const { request: r, at } of releaseAt.values()) if (performance.now() >= at) release(r.service, 'effect', r.key);
  for (const r of controls.filter(r => r.intent === 'post-abort')) {
    const record = await task(r);
    if (record.state.status === 'running' && record.state.checkpoint.phase === 'finish' && !postCancelled.has(r.id)) {
      postCancelled.add(r.id); await services[r.service].cancel(r.taskId);
    }
  }
  await observeTerminals();
  assert.ok(performance.now() - epoch < 8000); await delay(2);
}
// Drain already accepted tasks as well as the bounded caller queue before crash.
await wait(async () => {
  if (!controlsReleased && performance.now() - epoch >= 120) {
    await releaseControls();
  }
  for (const { request: r, at } of releaseAt.values()) if (performance.now() >= at) release(r.service, 'effect', r.key);
  for (const r of controls.filter(r => r.intent === 'post-abort')) {
    const record = await task(r);
    if (record.state.status === 'running' && record.state.checkpoint.phase === 'finish' && !postCancelled.has(r.id)) {
      postCancelled.add(r.id); await services[r.service].cancel(r.taskId);
    }
  }
  await observeTerminals();
  return ids.requests.filter(r => r.stage === stage && r.taskId && r.intent !== 'recover').every(r => ids.terminals[`${r.service}:${r.taskId}`]);
});
if (stage === 1) {
  for (let s = 0; s < 2; s++) {
    const r = { id: `s1-db${s}-recovery`, service: s, conversation: 0, stage, kind: 'control', intent: 'recover', hold: true,
      payload: `payload-s1-db${s}-recovery`, at_epoch_ms: Date.now() };
    assert.equal((await admit(r)).status, 'admit'); ids.requests.push(r); release(s, 'effect', r.key);
  }
}
const held = ids.requests.filter(r => r.taskId && !ids.terminals[`${r.service}:${r.taskId}`]);
if (stage < 2) {
  assert.equal(held.length, 2);
  await wait(async () => {
    for (const r of held) {
      const record = await task(r);
      if (record.state.status !== 'running' || record.state.checkpoint.phase !== 'finish') return false;
    }
    return true;
  });
} else {
  assert.equal(held.length, 0);
  for (const service of services) await service.harness.waitForIdle(service.context);
}
// Reuse stable request identities with a changed payload/current stale version.
for (let s = 0; s < 2; s++) {
  const r = controls.find(r => r.service === s && r.conversation === 0), service = services[s];
  assert.equal((await service.admit(ids.conversations[s][0], r.id, r.payload, stage + 1)).status, 'duplicate');
  assert.equal((await service.admit(ids.conversations[s][0], r.id, 'changed', stage + 1)).status, 'conflict');
  assert.equal((await service.admit(ids.conversations[s][0], `stale-${stage}`, 'none', 0)).status, 'unauthorized');
}
const states = [];
for (const service of services) { states.push(await service.snapshot()); service.flushCommitEvents(); }
save('identities.json', ids);
save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, mode, states, queue: {
  pending: queue.pending, maximumPending: queue.maximumPending, finished: queue.finished },
  elapsed_ms: performance.now() - started });
if (stage === 2) for (const service of services) { await service.close(); service.flushCommitEvents(); }
emit({ type: 'stage-ready', mode, held: held.length });
const flushStart = performance.now(); writeFileSync(resolve(output, `stage${stage}.jsonl`), events.join(''));
save(`stage${stage}-sink.json`, { events: events.length, bytes: callbackBytes, callback_ms: callbackMs,
  final_flush_ms: performance.now() - flushStart });
save(`stage${stage}-ready.json`, { stage, pid: process.pid, closed: stage === 2, mode, held: held.length });
if (stage < 2) { await delay(60000); throw new Error('Controller did not inject frozen crash'); }
