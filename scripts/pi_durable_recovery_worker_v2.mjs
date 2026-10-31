import assert from 'node:assert/strict';
import { appendFileSync, existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { openService, runtimeUrls } from '../experiments/pi_durable_service_v2.mjs';

const [runtimeDir, outputDir, stageText] = process.argv.slice(2);
const stage = Number(stageText);
const output = resolve(outputDir);
const started = performance.now();
const log = (value) => appendFileSync(resolve(output, `stage${stage}.jsonl`), JSON.stringify({ at: new Date().toISOString(), monotonic_ms: performance.now(), pid: process.pid, ...value }) + '\n');
globalThis.fetch = async () => { log({ type: 'network-access-denied' }); throw new Error('Network fetch forbidden in this workload'); };
const gates = new Set();
const phaseGate = async (phase, key, signal) => {
  while (!gates.has(`${phase}:${key}`)) {
    if (signal.aborted) throw signal.reason ?? new Error('cancelled');
    await delay(10, undefined, { signal });
  }
};
const service = await openService({ ...runtimeUrls(runtimeDir),
  database: resolve(output, 'service.sqlite'), phaseGate, emit: log });
const { harness, context } = service;
const save = (name, value) => {
  const path = resolve(output, name);
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, JSON.stringify(value, null, 2));
  renameSync(temporary, path);
};
const release = (phase, key) => gates.add(`${phase}:${key}`);
const wait = async (predicate) => {
  const deadline = performance.now() + 8000;
  while (!await predicate()) {
    if (performance.now() > deadline) throw new Error('Frozen8s condition deadline exceeded');
    await delay(10);
  }
};
const terminal = async (id) => (await harness.getTask(id, context))?.state.status === 'terminal';
const held = async (id, status = 'running') => {
  const record = await harness.getTask(id, context);
  assert.equal(record.state.status, status);
  assert.equal(record.state.checkpoint.phase, 'finish');
};
let ids;
if (stage === 0) {
  assert.ok(!existsSync(resolve(output, 'identities.json')));
  const a = await service.createSession();
  const b = await service.createSession();
  await service.authorize(a, 1, true);
  await service.authorize(b, 1, true);
  const one = await service.admit(a, 'one', 'effect-one', 1, true);
  const denied = await service.admit(b, 'denied', 'must-not-commit', 1);
  assert.equal(one.status, 'admit'); assert.equal(denied.status, 'admit');
  assert.equal((await service.admit(a, 'overflow', 'overflow', 1)).status, 'overloaded');
  assert.equal((await service.admit(a, 'one', 'effect-one', 1)).taskId, one.taskId);
  ids = { a, b, one, denied };
  save('identities.json', ids);
  harness.resume();
  await wait(async () => (await harness.inspect(context)).tasks.filter(t => t.state.kind === 'running').length === 2);
  await service.authorize(b, 2, false);
  release('effect', one.key); release('effect', denied.key);
  await wait(async () => (await service.snapshot())?.effects[one.key]?.count === 1 && await terminal(denied.taskId));
  const state = await service.snapshot();
  assert.deepEqual(state.denied, [denied.key]);
  assert.equal(Object.keys(state.effects).length, 1);
  await held(one.taskId);
} else {
  ids = JSON.parse(readFileSync(resolve(output, 'identities.json')));
  assert.equal((await harness.inspect(context)).scheduling, 'paused');
  assert.equal((await service.snapshot()).effects[ids.one.key].count, 1);
  if (stage === 1) {
    await held(ids.one.taskId, 'pending');
    assert.equal((await service.admit(ids.b, 'stale', 'not-authorized', 1)).status, 'unauthorized');
    await service.authorize(ids.b, 3, true);
    ids.two = await service.admit(ids.b, 'two', 'effect-two', 3, true);
    harness.resume();
    release('finish', ids.one.key); release('effect', ids.two.key);
    await wait(async () => await terminal(ids.one.taskId) && (await service.snapshot()).effects[ids.two.key]?.count === 1);
    const cancelled = await service.admit(ids.a, 'cancelled', 'must-not-commit', 1);
    assert.equal(cancelled.status, 'admit');
    await service.cancel(cancelled.taskId);
    await wait(() => terminal(cancelled.taskId));
    ids.cancelled = cancelled;
    ids.progress = await service.admit(ids.a, 'progress', 'effect-progress', 1);
    release('effect', ids.progress.key);
    await wait(() => terminal(ids.progress.taskId));
    const state = await service.snapshot();
    assert.equal(Object.keys(state.effects).length, 3);
    assert.deepEqual(state.cancelled, [cancelled.key]);
    assert.equal(Object.keys(state.active).length, 1);
    await held(ids.two.taskId);
    save('identities.json', ids);
  } else {
    assert.equal(stage, 2);
    await held(ids.two.taskId, 'pending');
    const duplicateOne = await service.admit(ids.a, 'one', 'effect-one', 1);
    const duplicateTwo = await service.admit(ids.b, 'two', 'effect-two', 3);
    assert.equal(duplicateOne.status, 'duplicate'); assert.equal(duplicateOne.taskId, ids.one.taskId);
    assert.equal(duplicateTwo.status, 'duplicate'); assert.equal(duplicateTwo.taskId, ids.two.taskId);
    assert.equal((await service.admit(ids.b, 'two', 'changed-payload', 3)).status, 'conflict');
    harness.resume(); release('finish', ids.two.key);
    await wait(() => terminal(ids.two.taskId));
    ids.final = await service.admit(ids.a, 'final', 'effect-final', 1);
    release('effect', ids.final.key);
    await wait(() => terminal(ids.final.taskId));
    await harness.waitForIdle(context);
    const state = await service.snapshot();
    assert.equal(Object.keys(state.effects).length, 4);
    assert.ok(Object.values(state.effects).every(effect => effect.count === 1));
    assert.equal(Object.keys(state.active).length, 0);
    save('identities-final.json', ids);
  }
}
const inspection = await harness.inspect(context);
const state = await service.snapshot();
service.flushCommitEvents();
save(`stage${stage}-snapshot.json`, { pid: process.pid, stage, state, inspection,
  elapsed_ms: performance.now() - started, memory: process.memoryUsage(), resourceUsage: process.resourceUsage() });
log({ type: 'stage-ready', stage });
if (stage < 2) {
  save(`stage${stage}-ready.json`, { stage, pid: process.pid, effectCount: Object.keys(state.effects).length });
  await delay(60000); // Parent must terminate this retained process; no graceful close at fault boundaries.
  throw new Error('Parent did not inject the preregistered crash');
} else {
  await service.close();
  save('stage2-ready.json', { stage, pid: process.pid, effectCount: 4, closed: true });
}
