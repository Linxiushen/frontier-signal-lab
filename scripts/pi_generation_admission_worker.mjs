// One fixed actual GenerationTask -> built-in Faux provider -> ToolTask workload.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { openGenerationService } from '../experiments/pi_generation_admission_service.mjs';

const [runtimeDirectory, outputDirectory, stageText] = process.argv.slice(2);
const stage = Number(stageText), output = resolve(outputDirectory), started = performance.now();
assert.ok([0, 1, 2].includes(stage));
const events = [], gates = new Set(), services = [], reached = new Set();
let callbackMs = 0;
const faults = new Map(), faultSeen = new Set(), failBefore = new Set();
const emit = e => {
  const at = performance.now();
  events.push(JSON.stringify({ stage, pid: process.pid, epoch_ms: Date.now(), monotonic_ms: at, ...e }) + '\n');
  if (e.key) reached.add(`${e.service}:${e.type}:${e.key}`);
  callbackMs += performance.now() - at;
};
globalThis.fetch = async () => { emit({ type: 'network-access-denied' }); throw new Error('No network allowed'); };
const save = (name, value) => {
  const p = resolve(output, name), tmp = `${p}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(value, null, 2)); renameSync(tmp, p);
};
const wait = async condition => {
  const deadline = performance.now() + 8000;
  while (!await condition()) { assert.ok(performance.now() < deadline, '8second condition bound'); await delay(2); }
};
const release = (service, phase, key) => gates.add(`${service}:${phase}:${key}`);
const ids = stage === 0 ? { conversations: [[], []], requests: [], recovered: [] } :
  JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8'));
for (let s = 0; s < 2; s++) {
  const service = await openGenerationService({ runtimeDirectory, providerApi: s === 0 ? undefined : 'frontier-faux-admission', database: resolve(output, `service${s}.sqlite`),
    admissionGate: async (phase, key) => {
      if (phase === 'before-reserve' && failBefore.delete(key)) {
        emit({ type: 'injected-before-reserve-error', service: s, key });
        throw new Error('Injected before-reserve error');
      }
      if (faults.get(key) === phase && !faultSeen.has(key)) {
        faultSeen.add(key); emit({ type: 'admission-gap-held', service: s, phase, key });
        while (true) await delay(2); // controller kills this exact pending host operation
      }
    },
    phaseGate: async (phase, key, signal) => {
      while (!gates.has(`${s}:${phase}:${key}`)) {
        signal?.throwIfAborted(); await delay(2, undefined, signal ? { signal } : undefined);
      }
      signal?.throwIfAborted();
    }, emit: e => emit({ service: s, ...e }) });
  services.push(service);
  if (stage === 0) for (let c = 0; c < 2; c++) ids.conversations[s].push(await service.createConversation());
  if (stage === 0) for (const id of ids.conversations[s]) await service.authorize(id, 1, true);
}
const reap = async () => {
  for (let s = 0; s < 2; s++) for (const r of await services[s].reap()) {
    ids.requests.find(q => q.service === s && q.key === r.key).terminal = r.submission;
    emit({ type: 'terminal', service: s, ...r });
  }
};
if (stage > 0) {
  const held = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
  assert.equal(held.length, 4);
  for (const r of held) {
    const state = await services[r.service].snapshot();
    if (r.intent === 'reserve-gap') assert.equal(state.effects[r.key], undefined);
    else assert.equal(state.effects[r.key].count, 1);
    emit({ type: 'recovery-before-resume', service: r.service, key: r.key, state });
    release(r.service, 'before-effect', r.key); release(r.service, 'after-effect', r.key);
  }
  for (const service of services) await service.reconcile();
  for (const r of held) {
    const state = await services[r.service].snapshot();
    r.submissionId = state.requests[r.key].submissionId;
    assert.ok(r.submissionId);
    ids.recovered.push({ stage, service: r.service, key: r.key, submissionId: r.submissionId, intent: r.intent });
  }
  for (const service of services) service.harness.resume();
  await wait(async () => { await reap(); return held.every(r => r.terminal); });
  for (let s = 0; s < 2; s++) for (const id of ids.conversations[s]) await services[s].authorize(id, stage + 1, true);
}
const controls = [];
async function admit(s, c, id, intent, holdPhase) {
  const r = { service: s, conversation: ids.conversations[s][c], requestId: id, payload: `payload-${id}`,
    version: stage + 1, intent, stage, offered_epoch_ms: Date.now() };
  r.key = `${r.conversation}:${id}`;
  if (holdPhase) {
    faults.set(r.key, holdPhase);
    services[s].admit(r.conversation, id, r.payload, r.version).catch(error => { throw error; });
    await wait(() => faultSeen.has(r.key));
    const state = await services[s].snapshot();
    assert.ok(state.requests[r.key] && state.active[r.key]);
    r.status = 'admit'; r.heldPhase = holdPhase;
    const native = await services[s].harness.commit(tx => tx.submissionByRequest(r.conversation, id), services[s].context);
    if (native) r.submissionId = native.id; // independent native observation, not a persisted host link
  } else Object.assign(r, await services[s].admit(r.conversation, id, r.payload, r.version));
  ids.requests.push(r); return r;
}
for (let s = 0; s < 2; s++) {
  for (let c = 0; c < 2; c++) {
    const intent = stage === 0 ? (c === 0 ? 'recover' : 'deny') :
      stage === 1 ? (c === 0 ? 'pre-abort' : 'post-abort') : 'commit';
    const r = await admit(s, c, `s${stage}-db${s}-control${c}`, intent, intent === 'recover' ? 'after-link' : undefined);
    assert.equal(r.status, 'admit'); controls.push(r);
  }
  const overflow = await admit(s, 0, `s${stage}-db${s}-overflow`, 'overload');
  assert.equal(overflow.status, 'overloaded');
}
await wait(() => controls.every(r => reached.has(`${r.service}:tool-enter:${r.key}`)));
// Native deduplication is checked independently of our host reservation map.
for (const r of controls) {
  const s = services[r.service];
  assert.equal((await s.admit(r.conversation, r.requestId, r.payload, r.version)).status, 'duplicate');
  assert.equal((await s.admit(r.conversation, r.requestId, 'changed', r.version)).status, 'conflict');
  assert.equal((await s.admit(r.conversation, `stale-${r.requestId}`, 'none', 0)).status, 'unauthorized');
  const replayed = await s.replay(r.conversation, r.requestId, r.key, r.payload, r.version);
  assert.equal(replayed.id, r.submissionId);
  emit({ type: 'native-duplicate', service: r.service, key: r.key, submissionId: replayed.id });
}
for (const r of controls) {
  if (r.intent === 'pre-abort') await services[r.service].cancelRequest(r.conversation, r.requestId);
  else {
    if (r.intent === 'deny') await services[r.service].authorize(r.conversation, 99, false);
    release(r.service, 'before-effect', r.key);
    if (r.intent === 'commit') release(r.service, 'after-effect', r.key);
  }
}
await wait(() => controls.filter(r => r.intent !== 'pre-abort').every(r => reached.has(`${r.service}:tool-effect:${r.key}`)));
for (const r of controls.filter(r => r.intent === 'post-abort')) await services[r.service].cancelRequest(r.conversation, r.requestId);
await wait(async () => { await reap(); return controls.filter(r => r.intent !== 'recover').every(r => r.terminal); });
if (stage === 1) for (let s = 0; s < 2; s++) {
  const r = await admit(s, 0, `s1-db${s}-recovery`, 'recover', 'after-link'); assert.equal(r.status, 'admit');
  release(s, 'before-effect', r.key);
  await wait(() => reached.has(`${s}:tool-effect:${r.key}`));
}
if (stage < 2) for (let s = 0; s < 2; s++) {
  if (stage === 0) await services[s].authorize(ids.conversations[s][1], 1, true);
  const phase = stage === 0 ? 'after-reserve' : 'after-submit';
  const intent = stage === 0 ? 'reserve-gap' : 'submit-gap';
  const r = await admit(s, 1, `s${stage}-db${s}-${intent}`, intent, phase);
  if (stage === 1) {
    await wait(() => reached.has(`${s}:tool-enter:${r.key}`));
    release(s, 'before-effect', r.key);
    await wait(() => reached.has(`${s}:tool-effect:${r.key}`));
  }
}
if (stage === 2) for (let s = 0; s < 2; s++) {
  const id = `s2-db${s}-before-reserve`, conversation = ids.conversations[s][0], key = `${conversation}:${id}`;
  failBefore.add(key);
  await assert.rejects(services[s].admit(conversation, id, `payload-${id}`, 3), /Injected before-reserve/);
  assert.equal((await services[s].snapshot()).requests[key], undefined);
  const r = await admit(s, 0, id, 'commit');
  release(s, 'before-effect', r.key); release(s, 'after-effect', r.key);
  await wait(async () => { await reap(); return Boolean(r.terminal); });
}
const held = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
assert.equal(held.length, stage < 2 ? 4 : 0);
const states = [];
for (const s of services) { states.push(await s.snapshot()); s.flush(); }
save('identities.json', ids); save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, states, held });
if (stage === 2) for (const service of services) { await service.harness.waitForIdle(service.context); await service.close(); service.flush(); }
emit({ type: 'ready', held: held.length });
const flushAt = performance.now(); writeFileSync(resolve(output, `stage${stage}.jsonl`), events.join(''));
save(`stage${stage}-sink.json`, { callback_ms: callbackMs, flush_ms: performance.now() - flushAt,
  bytes: Buffer.byteLength(events.join('')), events: events.length });
save(`stage${stage}-ready.json`, { stage, pid: process.pid, held: held.length, closed: stage === 2,
  elapsed_ms: performance.now() - started });
if (stage < 2) { await delay(60000); throw new Error('Controller did not kill fixed survivor stage'); }
