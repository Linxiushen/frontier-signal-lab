// Actual native scoped-v2 caller; distinct from the preserved failed concurrent suite.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { openScopedGenerationService, createEffectClient, effectIdentity, effectFingerprint } from '../experiments/pi_scoped_effect_http_client.mjs';
import { createTransportGate } from './pi_generation_http_worker.mjs';

export async function runWorker({ runtimeDirectory, outputDirectory, stage, baseURL }) {
  assert.ok(Number.isInteger(stage) && [0, 1, 2].includes(stage));
  const output = resolve(outputDirectory), started = performance.now();
  const events = [], services = [], clients = [], released = new Set(), cancelHolds = new Set(), marked = new Set();
  const errors = []; let callbackMs = 0;
  const emit = e => {
    const at = performance.now(); assert.ok(events.length < 2048, 'Finite event inventory');
    events.push(JSON.stringify({ stage, pid: process.pid, epoch_ms: Date.now(), monotonic_ms: at, ...e }) + '\n');
    callbackMs += performance.now() - at;
  };
  globalThis.fetch = async () => { emit({ type: 'network-access-denied' }); throw new Error('Only explicit bounded loopback HTTP allowed'); };
  const save = (name, value) => {
    const file = resolve(output, name), tmp = `${file}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(value, null, 2)); renameSync(tmp, file);
  };
  const wait = async condition => {
    const deadline = performance.now() + 8000;
    while (true) {
      if (errors.length) throw errors[0];
      if (await condition()) return;
      assert.ok(performance.now() < deadline, '8second condition bound'); await delay(2);
    }
  };
  const qualified = r => `${r.service}:${r.key}`;
  const ownEvents = (type, r) => events.map(JSON.parse).filter(e => e.type === type && e.service === r.service && e.key === r.key);
  const control = createEffectClient(baseURL, { scope: 'service0', emit: e => emit({ service: -1, ...e }) });
  const remoteSnapshot = async () => {
    const r = await control.request('GET', '/snapshot'); assert.equal(r.status, 200); return r.body;
  };
  const initial = await remoteSnapshot(); save(`effect-server${stage}-initial-snapshot.json`, initial);
  if (stage) assert.deepEqual(initial, JSON.parse(readFileSync(resolve(output, `effect-server${stage - 1}-final.json`), 'utf8')));
  assert.equal(initial.effects.length, [0, 0, 5][stage]);
  const ids = stage ? JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8')) :
    { conversations: [[], []], requests: [], recovered: [], retries: [], conflicts: [] };
  for (let s = 0; s < 2; s++) {
    const scope = `service${s}`;
    clients.push(createEffectClient(baseURL, { scope, emit: e => emit({ service: s, ...e }) }));
    const service = await openScopedGenerationService({ runtimeDirectory, effectBase: baseURL, effectScope: scope,
      transportOptions: { emit: e => emit({ service: s, ...e }) },
      database: resolve(output, `service${s}.sqlite`), providerApi: s ? 'frontier-faux-scoped' : undefined,
      phaseGate: createTransportGate({ service: s, released, emit }),
      cancellationGate: async (phase, key) => {
        const q = `${s}:${key}`;
        if (!cancelHolds.has(q)) return;
        assert.equal(phase, 'after-cancel-mark'); marked.add(q); emit({ type: 'cancel-mark-held', service: s, key });
        while (cancelHolds.has(q)) await delay(2);
      }, emit: e => emit({ service: s, ...e }) });
    services.push(service);
    if (!stage) for (let c = 0; c < 2; c++) ids.conversations[s].push(await service.createConversation());
  }
  // Independent native numeric identity allocators actually repeat across Sessions.
  assert.deepEqual(ids.conversations[0], ids.conversations[1]);
  const reap = async () => {
    for (let s = 0; s < 2; s++) {
      await services[s].reap(); const state = await services[s].snapshot();
      for (const r of ids.requests.filter(r => r.service === s && r.status === 'admit' && !r.terminal)) {
        if (state.requests[r.key]?.terminal) {
          r.terminal = state.requests[r.key].terminal; r.terminal_epoch_ms = Date.now();
          emit({ type: 'terminal', service: s, key: r.key, terminal: r.terminal, epoch_ms: r.terminal_epoch_ms });
        }
      }
    }
  };
  if (stage) {
    const pending = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
    assert.equal(pending.length, stage === 1 ? 4 : 1);
    for (const r of pending) emit({ type: 'recovery-before-resume', service: r.service, key: r.key, state: await services[r.service].snapshot() });
    for (const service of services) await service.reconcile();
    for (const r of pending) {
      ids.recovered.push({ stage, service: r.service, key: r.key, submissionId: r.submissionId });
      // Positive-control tools may replay their execute checkpoint. Reconciliation
      // already committed their receipt; let the same native chain finish.
      released.add(qualified(r));
    }
    for (const service of services) service.harness.resume();
    await wait(async () => { await reap(); return pending.every(r => r.terminal); });
    save(`stage${stage}-recovered.json`, { states: await Promise.all(services.map(s => s.snapshot())), server: await remoteSnapshot() });
  }
  async function remoteAuthorize(s, c, version, allowed) {
    const body = { scope: `service${s}`, conversation: ids.conversations[s][c], version, allowed };
    const r = await clients[s].request('POST', '/authority', body); assert.equal(r.status, 200);
    emit({ type: 'remote-authority', ...body });
  }
  for (let s = 0; s < 2; s++) for (let c = 0; c < 2; c++) {
    await services[s].authorize(ids.conversations[s][c], stage + 1, true);
    await remoteAuthorize(s, c, stage + 1, true);
  }
  function request(s, c, intent) {
    const requestId = `s${stage}-${intent}`, conversation = ids.conversations[s][c];
    // Neither canonical request IDs nor keys encode the service. Payloads differ.
    const r = { stage, service: s, scope: `service${s}`, conversation, requestId, intent, version: stage + 1,
      key: `${conversation}:${requestId}`, payload: `service${s}/${requestId}`, offered_epoch_ms: Date.now() };
    ids.requests.push(r); return r;
  }
  async function admit(r) {
    Object.assign(r, await services[r.service].admit(r.conversation, r.requestId, r.payload, r.version));
    assert.equal(r.status, r.intent === 'overload' ? 'overloaded' : 'admit');
    if (r.status === 'admit') assert.ok(Number.isSafeInteger(r.submissionId) && r.submissionId > 0);
    return r;
  }
  async function held(r) {
    await wait(async () => ownEvents('transport-held', r).length === 1 &&
      (await services[r.service].snapshot()).effectIntents[r.key]?.status === 'pending');
    assert.deepEqual((await services[r.service].snapshot()).effectIntents[r.key].identity,
      effectIdentity(r, r.conversation, r.scope));
  }
  async function markHold(r) {
    cancelHolds.add(qualified(r));
    services[r.service].cancelRequest(r.conversation, r.requestId).catch(error => errors.push(error));
    await wait(() => marked.has(qualified(r)));
    assert.equal((await services[r.service].snapshot()).requests[r.key].cancelled, true);
  }
  const current = [];
  for (let s = 0; s < 2; s++) {
    current.push(await admit(request(s, 0, ['revoke', 'post', 'final'][stage])));
    current.push(await admit(request(s, 1, ['cancel', 'live', 'final'][stage])));
    await admit(request(s, 0, 'overload'));
  }
  for (const r of current) await held(r);
  if (stage === 0) {
    await remoteAuthorize(0, 0, 1, false);
    assert.deepEqual((await services[0].snapshot()).authority[ids.conversations[0][0]], { version: 1, allowed: true });
    await markHold(current.find(r => r.service === 1 && r.intent === 'cancel'));
    // The unmodified counterpart in each other scope is the positive control.
  } else {
    if (stage === 1) {
      const post = current.find(r => r.service === 0 && r.intent === 'post');
      const hold = await clients[0].request('POST', '/hold', { scope: post.scope, key: post.key }); assert.equal(hold.status, 200);
      await services[0].authorize(ids.conversations[0][1], 2, false);
      emit({ type: 'host-authority-withdrawn', service: 0, conversation: ids.conversations[0][1], version: 2 });
    }
    for (const r of current) released.add(qualified(r));
    if (stage === 1) {
      await wait(async () => (await remoteSnapshot()).effects.length === 5);
      const post = current.find(r => r.service === 0 && r.intent === 'post');
      await wait(async () => { await reap(); return current.filter(r => r !== post).every(r => r.terminal); });
      const state = await services[0].snapshot();
      assert.equal(state.effectIntents[post.key].status, 'pending'); assert.equal(state.effects[post.key], undefined);
      await remoteAuthorize(0, 0, 2, false); await markHold(post);
    } else {
      await wait(async () => { await reap(); return current.every(r => r.terminal); });
      for (const r of current) {
        const retry = await services[r.service].admit(r.conversation, r.requestId, r.payload, r.version);
        assert.equal(retry.status, 'duplicate'); assert.equal(retry.submissionId, r.submissionId);
        ids.retries.push({ service: r.service, key: r.key, ...retry });
        const conflict = await services[r.service].admit(r.conversation, r.requestId, `changed/${r.payload}`, r.version);
        assert.equal(conflict.status, 'conflict'); ids.conflicts.push({ service: r.service, key: r.key, ...conflict });
      }
      for (const r of ids.requests.filter(r => r.intent === 'post')) {
        const identity = effectIdentity(r, r.conversation, r.scope), replay = await clients[r.service].apply(identity);
        assert.equal(replay.created, false); assert.deepEqual(replay.receipt, { ...identity, count: 1 });
        emit({ type: 'duplicate-effect-control', service: r.service, key: r.key, receipt: replay.receipt });
        const payload = `changed/${identity.payload}`, changed = { ...identity, payload, fingerprint: effectFingerprint(payload) };
        const response = await clients[r.service].request('POST', `/effects/${r.scope}/${encodeURIComponent(r.key)}`, changed);
        assert.equal(response.status, 409); assert.deepEqual(response.body, { error: 'identity-conflict' });
        emit({ type: 'changed-effect-control', service: r.service, key: r.key, status: response.status });
      }
    }
  }
  const states = await Promise.all(services.map(s => s.snapshot()));
  for (const service of services) service.flush();
  const pending = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
  assert.equal(pending.length, [4, 1, 0][stage]);
  const server = await remoteSnapshot(); assert.equal(server.effects.length, [0, 5, 9][stage]);
  save('identities.json', ids); save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, states, pending, server });
  if (stage === 2) for (const service of services) { await service.harness.waitForIdle(service.context); await service.close(); service.flush(); }
  assert.equal(events.map(JSON.parse).filter(e => ['network-access-denied', 'runtime-report'].includes(e.type)).length, 0);
  if (errors.length) throw errors[0]; emit({ type: 'ready', pending: pending.length });
  const flushAt = performance.now(), text = events.join(''); writeFileSync(resolve(output, `stage${stage}.jsonl`), text);
  save(`stage${stage}-sink.json`, { callback_ms: callbackMs, flush_ms: performance.now() - flushAt, bytes: Buffer.byteLength(text), events: events.length });
  save(`stage${stage}-ready.json`, { stage, pid: process.pid, pending: pending.length, closed: stage === 2, elapsed_ms: performance.now() - started });
  if (stage < 2) { await delay(60000); throw new Error('Controller did not kill fixed survivor stage'); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [runtimeDirectory, outputDirectory, stageText, baseURL] = process.argv.slice(2);
  await runWorker({ runtimeDirectory, outputDirectory, stage: Number(stageText), baseURL });
}
