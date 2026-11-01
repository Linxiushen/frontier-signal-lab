// Prepared complete native workload. Resource gate and separate freeze are required.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { openGenerationService } from '../experiments/pi_generation_cancellation_service.mjs';

const [runtimeDirectory, outputDirectory, stageText] = process.argv.slice(2);
const stage = Number(stageText), output = resolve(outputDirectory), started = performance.now();
assert.ok([0, 1, 2].includes(stage));
const events = [], gates = new Set(), services = [], heldHooks = new Set();
const pendingAdmissions = new Set(), pendingCancels = new Set();
let callbackMs = 0;
const emit = e => {
  const at = performance.now();
  events.push(JSON.stringify({ stage, pid: process.pid, epoch_ms: Date.now(), monotonic_ms: at, ...e }) + '\n');
  callbackMs += performance.now() - at;
};
globalThis.fetch = async () => { emit({ type: 'network-access-denied' }); throw new Error('No network allowed'); };
const save = (name, value) => {
  const path = resolve(output, name), tmp = `${path}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(value, null, 2)); renameSync(tmp, path);
};
const wait = async condition => {
  const deadline = performance.now() + 8000;
  while (!await condition()) { assert.ok(performance.now() < deadline, '8second condition bound'); await delay(2); }
};
const has = (type, r) => events.some(line => {
  const e = JSON.parse(line); return e.type === type && e.service === r.service && e.key === r.key;
});
const release = (r, phase) => gates.add(`${r.service}:${phase}:${r.key}`);
const ids = stage === 0 ? { conversations: [[], []], requests: [], recovered: [] } :
  JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8'));
for (let s = 0; s < 2; s++) {
  const hold = async (type, phase, key) => {
    heldHooks.add(`${type}:${key}`); emit({ type, phase, key, service: s });
    while (true) await delay(2);
  };
  const service = await openGenerationService({ runtimeDirectory,
    providerApi: s === 0 ? undefined : 'frontier-faux-cancellation', database: resolve(output, `service${s}.sqlite`),
    admissionGate: async (phase, key) => {
      if (phase === 'after-reserve' && pendingAdmissions.has(key)) await hold('reservation-held', phase, key);
    },
    cancellationGate: async (phase, key) => {
      if (pendingCancels.has(key)) await hold('cancel-mark-held', phase, key);
    },
    phaseGate: async (phase, key, signal) => {
      while (!gates.has(`${s}:${phase}:${key}`)) {
        signal?.throwIfAborted(); await delay(2, undefined, signal ? { signal } : undefined);
      }
      signal?.throwIfAborted();
    }, emit: e => emit({ service: s, ...e }) });
  services.push(service);
  if (stage === 0) for (let c = 0; c < 2; c++) ids.conversations[s].push(await service.createConversation());
}
const reap = async () => {
  for (let s = 0; s < 2; s++) {
    await services[s].reap();
    const state = await services[s].snapshot();
    for (const r of ids.requests.filter(q => q.service === s && q.status === 'admit' && !q.terminal)) {
      const terminal = state.requests[r.key]?.terminal;
      if (terminal) { r.terminal = terminal; emit({ type: 'terminal', service: s, key: r.key, terminal }); }
    }
  }
};
if (stage > 0) {
  const held = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
  assert.equal(held.length, 4);
  for (const r of held) emit({ type: 'recovery-before-resume', service: r.service, key: r.key,
    state: await services[r.service].snapshot() });
  // Do not release tool gates: reconciliation must consume the durable cancellation.
  for (const service of services) await service.reconcile();
  for (const r of held) ids.recovered.push({ stage, service: r.service, key: r.key, intent: r.intent,
    ...(r.submissionId === undefined ? {} : { submissionId: r.submissionId }) });
  for (const service of services) service.harness.resume();
  await wait(async () => { await reap(); return held.every(r => r.terminal); });
}
for (let s = 0; s < 2; s++) for (const id of ids.conversations[s]) await services[s].authorize(id, stage + 1, true);
async function admit(s, c, intent) {
  const requestId = `s${stage}-db${s}-${intent}-${c}`, conversation = ids.conversations[s][c];
  const r = { service: s, conversation, requestId, intent, stage, version: stage + 1,
    key: `${conversation}:${requestId}`, payload: `payload-${requestId}`, offered_epoch_ms: Date.now() };
  if (intent === 'pending-deny' || intent === 'pending-cancel') {
    pendingAdmissions.add(r.key);
    services[s].admit(conversation, requestId, r.payload, r.version).catch(error => { throw error; });
    await wait(() => heldHooks.has(`reservation-held:${r.key}`));
    const state = await services[s].snapshot(); assert.ok(state.requests[r.key] && state.active[r.key]);
    Object.assign(r, { status: 'admit', heldPhase: 'after-reserve' });
  } else Object.assign(r, await services[s].admit(conversation, requestId, r.payload, r.version));
  ids.requests.push(r); return r;
}
async function markAndHold(r) {
  pendingCancels.add(r.key);
  services[r.service].cancelRequest(r.conversation, r.requestId).catch(error => { throw error; });
  await wait(() => heldHooks.has(`cancel-mark-held:${r.key}`));
  assert.equal((await services[r.service].snapshot()).requests[r.key].cancelled, true);
}
const controls = [];
for (let s = 0; s < 2; s++) {
  for (let c = 0; c < 2; c++) {
    const intent = stage === 0 ? (c === 0 ? 'pre-cancel' : 'pending-deny') :
      stage === 1 ? (c === 0 ? 'post-cancel' : 'pending-cancel') : 'commit';
    const r = await admit(s, c, intent); assert.equal(r.status, 'admit'); controls.push(r);
  }
  assert.equal((await admit(s, 0, 'overload')).status, 'overloaded');
}
for (const r of controls.filter(r => r.submissionId !== undefined)) {
  await wait(() => has('tool-enter', r));
  const service = services[r.service];
  assert.equal((await service.admit(r.conversation, r.requestId, r.payload, r.version)).status, 'duplicate');
  assert.equal((await service.admit(r.conversation, r.requestId, 'changed', r.version)).status, 'conflict');
  assert.equal((await service.admit(r.conversation, `stale-${r.requestId}`, 'none', 0)).status, 'unauthorized');
  const native = await service.replay(r.conversation, r.requestId, r.key, r.payload, r.version);
  assert.equal(native.id, r.submissionId);
  emit({ type: 'native-duplicate', service: r.service, key: r.key, submissionId: native.id });
}
for (const r of controls) {
  if (r.intent === 'pending-deny') await services[r.service].authorize(r.conversation, 99, false);
  else if (r.intent === 'pre-cancel' || r.intent === 'pending-cancel') await markAndHold(r);
  else {
    release(r, 'before-effect');
    await wait(() => has('tool-effect', r));
    if (r.intent === 'post-cancel') await markAndHold(r);
    else release(r, 'after-effect');
  }
}
if (stage === 2) await wait(async () => { await reap(); return controls.every(r => r.terminal); });
const held = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
assert.equal(held.length, stage < 2 ? 4 : 0);
const states = [];
for (const service of services) { states.push(await service.snapshot()); service.flush(); }
save('identities.json', ids); save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, states, held });
if (stage === 2) for (const service of services) { await service.harness.waitForIdle(service.context); await service.close(); service.flush(); }
emit({ type: 'ready', held: held.length });
const flushAt = performance.now(); writeFileSync(resolve(output, `stage${stage}.jsonl`), events.join(''));
save(`stage${stage}-sink.json`, { callback_ms: callbackMs, flush_ms: performance.now() - flushAt,
  bytes: Buffer.byteLength(events.join('')), events: events.length });
save(`stage${stage}-ready.json`, { stage, pid: process.pid, held: held.length, closed: stage === 2,
  elapsed_ms: performance.now() - started });
if (stage < 2) { await delay(60000); throw new Error('Controller did not kill fixed survivor stage'); }
