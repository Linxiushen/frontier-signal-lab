// Fixed offered-load caller on the unchanged, previously accepted native adapter.
import assert from 'node:assert/strict';
import { appendFileSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { openService, runtimeUrls } from '../experiments/pi_durable_service_v2.mjs';

const [runtimeDir, outputDir, stageText, capacityText, sink] = process.argv.slice(2);
const stage = Number(stageText), capacity = Number(capacityText), output = resolve(outputDir);
assert.ok([0, 1, 2].includes(stage));
assert.ok([2, 4].includes(capacity));
assert.ok(['direct', 'buffered'].includes(sink));
const events = [], gates = new Set();
const started = performance.now();
let sinkCalls = 0, sinkBytes = 0, sinkMs = 0;
const logPath = resolve(output, `stage${stage}.jsonl`);
const emit = value => {
  const begin = performance.now();
  const line = JSON.stringify({ at: new Date().toISOString(), monotonic_ms: performance.now(), pid: process.pid, stage, ...value }) + '\n';
  if (sink === 'direct') appendFileSync(logPath, line);
  else events.push(line);
  sinkBytes += Buffer.byteLength(line); sinkCalls += 1; sinkMs += performance.now() - begin;
};
globalThis.fetch = async () => { emit({ type: 'network-access-denied' }); throw new Error('No network/provider access in this workload'); };
const phaseGate = async (phase, key, signal) => {
  while (!gates.has(`${phase}:${key}`)) {
    if (signal.aborted) throw signal.reason ?? new Error('cancelled');
    await delay(5, undefined, { signal });
  }
};
const service = await openService({ ...runtimeUrls(runtimeDir), database: resolve(output, 'service.sqlite'),
  capacity, phaseGate, emit });
const { harness, context } = service;
const save = (name, value) => {
  const path = resolve(output, name), temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, JSON.stringify(value, null, 2)); renameSync(temporary, path);
};
const wait = async predicate => {
  const end = performance.now() + 8000;
  while (!await predicate()) {
    if (performance.now() > end) throw new Error('Frozen8s condition deadline exceeded');
    await delay(5);
  }
};
const release = (phase, key) => gates.add(`${phase}:${key}`);
const task = id => harness.getTask(id, context);
let ids;
if (stage === 0) {
  ids = { sessions: [], versions: [1, 1, 1, 1], requests: [], terminals: {} };
  for (let i = 0; i < 4; i++) {
    const session = await service.createSession(); ids.sessions.push(session);
    await service.authorize(session, 1, true);
  }
} else {
  ids = JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8'));
  assert.equal((await harness.inspect(context)).scheduling, 'paused');
  const recovered = ids.requests.filter(r => r.status === 'admit' && !ids.terminals[r.taskId]);
  for (const request of recovered) {
    const record = await task(request.taskId);
    assert.equal(record.state.status, 'pending'); assert.equal(record.state.checkpoint.phase, 'finish');
    emit({ type: 'recovered-finish', key: request.key, taskId: request.taskId, stage });
    release('finish', request.key);
  }
  harness.resume();
  for (const request of recovered) {
    await wait(async () => (await task(request.taskId)).state.status === 'terminal');
    ids.terminals[request.taskId] = { at_epoch_ms: Date.now(), outcome: (await task(request.taskId)).state.outcome };
  }
  if (stage === 1) {
    ids.versions[1] = 3; await service.authorize(ids.sessions[1], 3, true);
  }
  assert.equal(Object.keys((await service.snapshot()).active).length, 0);
}

// Four unique arrivals are offered sequentially without waiting for completion.
// Every effect is held until all four admission calls and three probes finish.
const burst = [];
for (let i = 0; i < 4; i++) {
  const session = ids.sessions[i], requestId = `s${stage}-r${i}`, payload = `effect-${requestId}`;
  const at = Date.now();
  const result = await service.admit(session, requestId, payload, ids.versions[i], stage < 2);
  assert.equal(result.status, i < capacity ? 'admit' : 'overloaded');
  const request = { stage, index: i, session, requestId, payload, at_epoch_ms: at, ...result };
  ids.requests.push(request); burst.push(request);
}
const first = burst[0];
const duplicate = await service.admit(first.session, first.requestId, first.payload, ids.versions[0]);
assert.equal(duplicate.status, 'duplicate'); assert.equal(duplicate.taskId, first.taskId);
assert.equal((await service.admit(first.session, first.requestId, 'changed', ids.versions[0])).status, 'conflict');
assert.equal((await service.admit(first.session, `stale-${stage}`, 'must-not-commit', 0)).status, 'unauthorized');
if (stage === 0) {
  await service.authorize(ids.sessions[1], 2, false); ids.versions[1] = 2;
  harness.resume();
} else if (stage === 1) {
  // The only supported cancellation guarantee here is cancellation before effect release.
  await service.cancel(first.taskId);
  await wait(async () => (await task(first.taskId)).state.status === 'terminal');
}
await delay(10); // Same injected service delay in every arm; not real provider work.
for (const request of burst.filter(r => r.status === 'admit')) {
  if (!(stage === 1 && request.index === 0)) release('effect', request.key);
}
await wait(async () => {
  for (const request of burst.filter(r => r.status === 'admit')) {
    const record = await task(request.taskId);
    if ((stage === 0 && request.index === 1) || (stage === 1 && request.index === 0) || stage === 2) {
      if (record.state.status !== 'terminal') return false;
    } else if (record.state.status !== 'running' || record.state.checkpoint.phase !== 'finish') return false;
  }
  return true;
});
for (const request of burst.filter(r => r.status === 'admit')) {
  const record = await task(request.taskId);
  if (record.state.status === 'terminal') ids.terminals[request.taskId] = { at_epoch_ms: Date.now(), outcome: record.state.outcome };
}
if (stage === 2) await harness.waitForIdle(context);
const state = await service.snapshot(), inspection = await harness.inspect(context);
service.flushCommitEvents();
save('identities.json', ids);
save(`stage${stage}-snapshot.json`, { pid: process.pid, stage, capacity, sink, state, inspection,
  elapsed_ms: performance.now() - started, memory: process.memoryUsage(), resourceUsage: process.resourceUsage() });
if (stage === 2) { await service.close(); service.flushCommitEvents(); }
emit({ type: 'stage-ready', stage, capacity, sink });
// Buffered and direct modes retain the same event schema. The final buffered
// write is timed separately; commit subscription/storage observation is common.
const flushStart = performance.now();
if (sink === 'buffered') writeFileSync(logPath, events.join(''));
const finalFlushMs = performance.now() - flushStart;
save(`stage${stage}-sink.json`, { sink, sinkCalls, sinkBytes, callback_ms: sinkMs, final_flush_ms: finalFlushMs,
  scope: 'Serialization+callback sink cost; final flush separate. Common native subscription/snapshot/controller costs are not isolated.' });
if (stage < 2) {
  save(`stage${stage}-ready.json`, { stage, pid: process.pid, effectCount: Object.keys(state.effects).length });
  await delay(60000); throw new Error('Controller did not inject the frozen crash');
} else {
  save('stage2-ready.json', { stage, pid: process.pid, effectCount: Object.keys(state.effects).length, closed: true });
}
