// Complete finite caller for a separately frozen native error/collision suite.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { openGenerationService } from '../experiments/pi_generation_conflict_service.mjs';

const [runtimeDirectory, outputDirectory, stageText] = process.argv.slice(2);
const stage = Number(stageText), output = resolve(outputDirectory), started = performance.now();
assert.ok([0, 1, 2].includes(stage));
const events = [], gates = new Set(), services = [], held = new Set(), reserveHolds = new Set(), cancelHolds = new Set();
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
const ownEvents = (type, r) => events.map(JSON.parse).filter(e => e.type === type && e.service === r.service && e.key === r.key);
const release = (r, phase) => gates.add(`${r.service}:${phase}:${r.key}`);
const ids = stage === 0 ? { conversations: [[], []], requests: [], native: [], recovered: [] } :
  JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8'));
for (let s = 0; s < 2; s++) {
  const service = await openGenerationService({ runtimeDirectory,
    providerApi: s === 0 ? undefined : 'frontier-faux-conflict', database: resolve(output, `service${s}.sqlite`),
    admissionGate: async (phase, key) => {
      if (phase !== 'after-reserve' || !reserveHolds.has(key)) return;
      held.add(`reserve:${key}`); emit({ type: 'reservation-held', service: s, key });
      while (reserveHolds.has(key)) await delay(2);
    },
    cancellationGate: async (phase, key) => {
      if (!cancelHolds.has(key)) return;
      held.add(`cancel:${key}`); emit({ type: 'cancel-mark-held', phase, service: s, key });
      while (true) await delay(2);
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
    for (const r of ids.requests.filter(q => q.service === s && q.intent !== 'overload' && !q.terminal)) {
      const terminal = state.requests[r.key]?.terminal;
      if (terminal) { r.terminal = terminal; emit({ type: 'terminal', service: s, key: r.key, terminal }); }
    }
  }
};
if (stage > 0) {
  const pending = ids.requests.filter(r => r.intent !== 'overload' && !r.terminal);
  assert.equal(pending.length, stage === 1 ? 4 : 2);
  for (const r of pending) emit({ type: 'recovery-before-resume', service: r.service, key: r.key,
    state: await services[r.service].snapshot() });
  for (const service of services) await service.reconcile();
  for (const r of pending) ids.recovered.push({ stage, service: r.service, key: r.key,
    ...(r.submissionId === undefined ? {} : { submissionId: r.submissionId }) });
  for (const service of services) service.harness.resume();
  await wait(async () => { await reap(); return pending.every(r => r.terminal); });
}
for (let s = 0; s < 2; s++) for (const id of ids.conversations[s]) await services[s].authorize(id, stage + 1, true);
function request(s, c, intent) {
  const conversation = ids.conversations[s][c], requestId = `s${stage}-db${s}-${intent}-${c}`;
  const r = { service: s, conversation, requestId, intent, stage, version: stage + 1,
    key: `${conversation}:${requestId}`, payload: `payload-${requestId}`, offered_epoch_ms: Date.now() };
  ids.requests.push(r); return r;
}
const nativeRow = r => ids.native.push({ ...r });
async function admit(r) {
  Object.assign(r, await services[r.service].admit(r.conversation, r.requestId, r.payload, r.version));
  assert.equal(r.status, r.intent === 'overload' ? 'overloaded' : 'admit');
  if (r.submissionId !== undefined) nativeRow(r);
  return r;
}
async function markHold(r) {
  cancelHolds.add(r.key);
  services[r.service].cancelRequest(r.conversation, r.requestId).catch(error => { throw error; });
  await wait(() => held.has(`cancel:${r.key}`));
  assert.equal((await services[r.service].snapshot()).requests[r.key].cancelled, true);
}
if (stage === 0) {
  for (let s = 0; s < 2; s++) {
    const control = await admit(request(s, 0, 'pre-abort'));
    await wait(() => ownEvents('tool-enter', control).length === 1);
    const busy = request(s, 0, s === 0 ? 'busy-deny' : 'busy-cancel');
    await assert.rejects(services[s].admit(busy.conversation, busy.requestId, busy.payload, busy.version), error => {
      assert.equal(error.name, 'ConversationBusy'); emit({ type: 'native-busy', service: s, key: busy.key, name: error.name, message: error.message }); return true;
    });
    busy.status = 'reserved-error';
    const state = await services[s].snapshot();
    assert.equal(state.active[busy.key], true); assert.equal(state.requests[busy.key].submissionId, undefined);
    await admit(request(s, 1, 'overload'));
    if (s === 0) await services[s].authorize(busy.conversation, 99, false);
    else await markHold(busy);
    await markHold(control);
  }
} else if (stage === 1) {
  for (let s = 0; s < 2; s++) {
    for (const [c, intent] of [[0, 'type-collision'], [1, 'content-collision']]) {
      const r = request(s, c, intent); reserveHolds.add(r.key);
      const pending = services[s].admit(r.conversation, r.requestId, r.payload, r.version);
      await wait(() => held.has(`reserve:${r.key}`));
      if (c === 0) {
        const conversation = await services[s].harness.conversation(r.conversation, services[s].context);
        const original = await conversation.submit({ type: 'write', requestId: r.requestId,
          entry: { kind: 'frontier.fixture', data: { original: r.key } } }, services[s].context);
        r.nativeSubmissionId = original.id;
        await assert.rejects(services[s].replay(r.conversation, r.requestId, r.key, r.payload, r.version), error => {
          assert.equal(error.message, `Request ${r.requestId} already identifies a submission of type write`);
          emit({ type: 'native-type-error', service: s, key: r.key, name: error.name, message: error.message, submissionId: original.id }); return true;
        });
      } else {
        const original = await services[s].replay(r.conversation, r.requestId, r.key, 'foreign-' + r.payload, r.version);
        r.nativeSubmissionId = original.id;
        await wait(() => ownEvents('tool-enter', r).length === 1);
        const replay = await services[s].replay(r.conversation, r.requestId, r.key, r.payload, r.version);
        assert.equal(replay.id, original.id);
        const before = await original.status(services[s].context);
        await services[s].cancelRequest(r.conversation, r.requestId);
        const after = await original.status(services[s].context);
        assert.deepEqual(after, before); assert.equal(after.status, 'placed');
        emit({ type: 'native-content-reuse', service: s, key: r.key, submissionId: original.id, before, after });
      }
      reserveHolds.delete(r.key); Object.assign(r, await pending);
      assert.equal(r.submissionId, undefined);
      const state = await services[s].snapshot();
      assert.deepEqual(state.requests[r.key].terminal, { status: 'native-conflict', nativeSubmissionId: r.nativeSubmissionId,
        nativeType: c === 0 ? 'write' : 'input' });
      assert.equal(state.active[r.key], undefined);
      if (c === 1) {
        // The fixture owner aborts this uniquely in-flight conversation, then waits for
        // its exact original submission. The native placed-input abort is conversation-wide.
        // The host quarantine above must leave it placed and unchanged.
        await services[s].cancel(r.conversation);
        const original = await services[s].harness.submission(r.nativeSubmissionId, services[s].context);
        const terminal = await original.wait(services[s].context);
        nativeRow({ ...r, payload: 'foreign-' + r.payload, submissionId: r.nativeSubmissionId, terminal, intent: 'pre-abort' });
        emit({ type: 'fixture-native-dispose', service: s, key: r.key, submissionId: r.nativeSubmissionId, terminal });
      }
      await reap();
    }
    const control = await admit(request(s, 0, 'post-abort'));
    await wait(() => ownEvents('tool-enter', control).length === 1);
    release(control, 'before-effect'); await wait(() => ownEvents('tool-effect', control).length === 1);
    await markHold(control);
  }
} else {
  const controls = [];
  for (let s = 0; s < 2; s++) {
    for (let c = 0; c < 2; c++) controls.push(await admit(request(s, c, 'commit')));
    await admit(request(s, 0, 'overload'));
  }
  for (const r of controls) {
    await wait(() => ownEvents('tool-enter', r).length === 1);
    release(r, 'before-effect'); await wait(() => ownEvents('tool-effect', r).length === 1); release(r, 'after-effect');
  }
  await wait(async () => { await reap(); return controls.every(r => r.terminal); });
}
// Refresh original native terminal records without inventing provider replay.
for (const r of ids.native) {
  const submission = await services[r.service].harness.submission(r.submissionId, services[r.service].context);
  const current = await submission.status(services[r.service].context);
  if (['done', 'unanswered'].includes(current.status)) r.terminal = current;
}
const states = [];
for (const service of services) { states.push(await service.snapshot()); service.flush(); }
const pending = ids.requests.filter(r => r.intent !== 'overload' && !r.terminal);
assert.equal(pending.length, stage === 0 ? 4 : stage === 1 ? 2 : 0);
save('identities.json', ids); save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, states, pending });
if (stage === 2) for (const service of services) { await service.harness.waitForIdle(service.context); await service.close(); service.flush(); }
emit({ type: 'ready', pending: pending.length });
const flushAt = performance.now(); writeFileSync(resolve(output, `stage${stage}.jsonl`), events.join(''));
save(`stage${stage}-sink.json`, { callback_ms: callbackMs, flush_ms: performance.now() - flushAt,
  bytes: Buffer.byteLength(events.join('')), events: events.length });
save(`stage${stage}-ready.json`, { stage, pid: process.pid, pending: pending.length, closed: stage === 2,
  elapsed_ms: performance.now() - started });
if (stage < 2) { await delay(60000); throw new Error('Controller did not kill fixed survivor stage'); }
