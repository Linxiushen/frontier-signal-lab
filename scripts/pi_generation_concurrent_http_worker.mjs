// Complete finite caller for a separately frozen native ToolTask/HTTP effect suite.
// Importing its gate for pure tests does not open the optional native runtime.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { createConcurrentAdmissionRound } from '../experiments/pi_concurrent_admission.mjs';
import { openGenerationService } from '../experiments/pi_generation_http_service.mjs';
import { createEffectClient, effectFingerprint, effectIdentity } from '../experiments/pi_effect_http_client.mjs';

export function createTransportGate({ service, released, emit }) {
  return async (phase, key, signal) => {
    assert.ok(['before-effect', 'before-transport', 'after-effect'].includes(phase), 'Unknown effect phase');
    signal?.throwIfAborted();
    if (phase !== 'before-transport') return;
    emit({ type: 'transport-held', service, key });
    while (!released.has(`${service}:${key}`)) {
      signal?.throwIfAborted();
      await delay(2, undefined, signal ? { signal } : undefined);
    }
    signal?.throwIfAborted();
    emit({ type: 'transport-released', service, key });
  };
}

export async function runWorker({ runtimeDirectory, outputDirectory, stage, baseURL }) {
  assert.ok(Number.isInteger(stage) && [0, 1, 2].includes(stage), 'Exactly three finite worker stages');
  assert.equal(typeof runtimeDirectory, 'string');
  const output = resolve(outputDirectory), started = performance.now();
  const events = [], services = [], clients = [], released = new Set(), cancelHolds = new Set(), held = new Set();
  const backgroundErrors = [], admissionRounds = [];
  let callbackMs = 0;
  const emit = e => {
    const at = performance.now();
    assert.ok(events.length < 2048, 'Finite trace event ceiling');
    events.push(JSON.stringify({ stage, pid: process.pid, epoch_ms: Date.now(), monotonic_ms: at, ...e }) + '\n');
    callbackMs += performance.now() - at;
  };
  globalThis.fetch = async () => { emit({ type: 'network-access-denied' }); throw new Error('Only explicit bounded node:http loopback transport allowed'); };
  const save = (name, value) => {
    const path = resolve(output, name), tmp = `${path}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(value, null, 2)); renameSync(tmp, path);
  };
  const wait = async condition => {
    const deadline = performance.now() + 8000;
    while (true) {
      if (backgroundErrors.length) throw backgroundErrors[0];
      if (await condition()) return;
      assert.ok(performance.now() < deadline, '8second condition bound');
      await delay(2);
    }
  };
  const ownEvents = (type, r) => events.map(JSON.parse).filter(e => e.type === type && e.service === r.service && e.key === r.key);
  const release = r => released.add(`${r.service}:${r.key}`);
  const controlClient = createEffectClient(baseURL, { emit: e => emit({ service: -1, ...e }) });
  const serverSnapshot = async () => {
    const response = await controlClient.request('GET', '/snapshot');
    assert.equal(response.status, 200);
    return response.body;
  };
  const initialServer = await serverSnapshot();
  save(`effect-server${stage}-initial-snapshot.json`, initialServer);
  if (stage > 0) {
    const priorFinal = JSON.parse(readFileSync(resolve(output, `effect-server${stage - 1}-final.json`), 'utf8'));
    assert.deepEqual(initialServer, priorFinal, 'Separate effect DB survives the server process reopen exactly');
  }
  assert.equal(initialServer.effects.length, stage === 2 ? 4 : 0);
  const ids = stage === 0 ? { conversations: [[], []], requests: [], native: [], recovered: [] } :
    JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8'));
  for (let s = 0; s < 2; s++) {
    const client = createEffectClient(baseURL, { emit: e => emit({ service: s, ...e }) });
    clients.push(client);
    const round = createConcurrentAdmissionRound({ emit: e => emit({ service: s, ...e }) });
    admissionRounds.push(round);
    const service = await openGenerationService({ runtimeDirectory, admissionGate: round.gate,
      providerApi: s === 0 ? undefined : 'frontier-faux-http', database: resolve(output, `service${s}.sqlite`),
      effectClient: client, effectScope: `service${s}`,
      cancellationGate: async (phase, key) => {
        if (!cancelHolds.has(key)) return;
        assert.equal(phase, 'after-cancel-mark');
        held.add(`cancel:${key}`); emit({ type: 'cancel-mark-held', phase, service: s, key });
        while (cancelHolds.has(key)) await delay(2);
      },
      phaseGate: createTransportGate({ service: s, released, emit }),
      emit: e => emit({ service: s, ...e }) });
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
    // Each adapter reconciles independent effect intents before resuming native work.
    for (const service of services) await service.reconcile();
    for (const r of pending) ids.recovered.push({ stage, service: r.service, key: r.key, submissionId: r.submissionId });
    for (const service of services) service.harness.resume();
    await wait(async () => { await reap(); return pending.every(r => r.terminal); });
  }
  async function remoteAuthorize(service, conversation, version, allowed) {
    const scope = `service${service}`;
    const response = await controlClient.request('POST', '/authority', { scope, conversation, version, allowed });
    assert.equal(response.status, 200);
    emit({ type: 'remote-authority', scope, conversation, version, allowed });
  }
  // Authority advances only after recovering the prior version's exact intents.
  for (let s = 0; s < 2; s++) for (const conversation of ids.conversations[s]) {
    await services[s].authorize(conversation, stage + 1, true);
    await remoteAuthorize(s, conversation, stage + 1, true);
  }
  function request(s, c, intent) {
    const conversation = ids.conversations[s][c], requestId = `s${stage}-db${s}-${intent}-${c}`;
    const r = { service: s, conversation, requestId, intent, stage, version: stage + 1,
      key: `${conversation}:${requestId}`, payload: `payload-${requestId}`, offered_epoch_ms: Date.now() };
    ids.requests.push(r); return r;
  }
  function recordAdmission(r, value) {
    Object.assign(r, value);
    assert.equal(r.status, r.intent === 'overload' ? 'overloaded' : 'admit');
    if (r.submissionId !== undefined) ids.native.push({ ...r });
    if (r.intent !== 'overload') assert.ok(Number.isSafeInteger(r.submissionId) && r.submissionId > 0);
    return r;
  }
  async function admit(r) {
    return recordAdmission(r, await services[r.service].admit(r.conversation, r.requestId, r.payload, r.version));
  }
  async function admitPair(s, intents, pair = intents.map((intent, c) => request(s, c, intent))) {
    const values = await admissionRounds[s].run(services[s], pair, `stage${stage}-service${s}`);
    pair.forEach((r, i) => recordAdmission(r, values[i]));
    const first = pair[0], changed = `changed-${first.payload}`;
    const result = await services[s].admit(first.conversation, first.requestId, changed, first.version);
    assert.deepEqual(result, { status: 'conflict', key: first.key });
    emit({ type: 'concurrent-content-conflict', round: `stage${stage}-service${s}`, key: first.key,
      changed_payload: changed, result });
    return pair;
  }
  async function intentHeld(r) {
    await wait(async () => {
      const state = await services[r.service].snapshot(), intent = state.effectIntents[r.key];
      return ownEvents('transport-held', r).length === 1 && intent?.status === 'pending';
    });
    const state = await services[r.service].snapshot();
    assert.deepEqual(state.effectIntents[r.key].identity, effectIdentity(r, r.conversation, `service${r.service}`));
  }
  async function markHold(r) {
    cancelHolds.add(r.key);
    services[r.service].cancelRequest(r.conversation, r.requestId).catch(error => backgroundErrors.push(error));
    await wait(() => held.has(`cancel:${r.key}`));
    assert.equal((await services[r.service].snapshot()).requests[r.key].cancelled, true);
  }
  if (stage === 0) {
    for (let s = 0; s < 2; s++) {
      const [denied, cancelled] = await admitPair(s, ['remote-deny', 'pre-cancel']);
      await intentHeld(denied); await intentHeld(cancelled);
      await admit(request(s, 0, 'overload'));
      await remoteAuthorize(s, denied.conversation, 1, false);
      assert.deepEqual((await services[s].snapshot()).authority[denied.conversation], { version: 1, allowed: true });
      await markHold(cancelled);
    }
  } else if (stage === 1) {
    for (let s = 0; s < 2; s++) {
      const post = request(s, 0, 'post-cancel');
      const hold = await controlClient.request('POST', '/hold', { key: post.key });
      assert.equal(hold.status, 200);
      const [, normal] = await admitPair(s, ['post-cancel', 'commit'], [post, request(s, 1, 'commit')]);
      await intentHeld(post); await intentHeld(normal);
      release(post); release(normal);
      await wait(async () => {
        const remote = await serverSnapshot();
        return [post.key, normal.key].every(key => remote.effects.some(effect => effect.key === key && effect.count === 1));
      });
      await wait(async () => { await reap(); return Boolean(normal.terminal); });
      // The server committed and is withholding the post-effect reply. The native
      // request stays unacknowledged until a fresh process looks up the same key.
      const state = await services[s].snapshot();
      assert.equal(state.effectIntents[post.key].status, 'pending');
      assert.equal(state.effects[post.key], undefined);
      await markHold(post);
    }
  } else {
    const controls = [];
    for (let s = 0; s < 2; s++) {
      controls.push(...await admitPair(s, ['commit', 'commit']));
      await admit(request(s, 0, 'overload'));
    }
    for (const r of controls) { await intentHeld(r); release(r); }
    await wait(async () => { await reap(); return controls.every(r => r.terminal); });
    for (const r of ids.requests.filter(r => r.intent === 'post-cancel')) {
      const identity = effectIdentity(r, r.conversation, `service${r.service}`), duplicate = await clients[r.service].apply(identity);
      assert.equal(duplicate.created, false); assert.deepEqual(duplicate.receipt, { ...identity, count: 1 });
      emit({ type: 'duplicate-effect-control', service: r.service, key: r.key, status: 200, receipt: duplicate.receipt });
      const payload = `changed-${identity.payload}`;
      const changed = { ...identity, payload, fingerprint: effectFingerprint(payload) };
      const conflict = await clients[r.service].request('POST', `/effects/${encodeURIComponent(r.key)}`, changed);
      assert.equal(conflict.status, 409); assert.deepEqual(conflict.body, { error: 'identity-conflict' });
      emit({ type: 'changed-effect-control', service: r.service, key: r.key, status: conflict.status, payload, fingerprint: changed.fingerprint });
    }
  }
  for (const r of ids.native) {
    const submission = await services[r.service].harness.submission(r.submissionId, services[r.service].context);
    const current = await submission.status(services[r.service].context);
    if (['done', 'unanswered'].includes(current.status)) r.terminal = current;
  }
  const states = [];
  for (const service of services) { states.push(await service.snapshot()); service.flush(); }
  const pending = ids.requests.filter(r => r.intent !== 'overload' && !r.terminal);
  assert.equal(pending.length, stage === 0 ? 4 : stage === 1 ? 2 : 0);
  const server = await serverSnapshot();
  assert.equal(server.effects.length, stage === 0 ? 0 : stage === 1 ? 4 : 8);
  save('identities.json', ids);
  save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, states, pending, server });
  save(`effect-server${stage}-ready-snapshot.json`, server);
  if (stage === 2) for (const service of services) {
    await service.harness.waitForIdle(service.context); await service.close(); service.flush();
  }
  if (backgroundErrors.length) throw backgroundErrors[0];
  emit({ type: 'ready', pending: pending.length });
  const flushAt = performance.now(); writeFileSync(resolve(output, `stage${stage}.jsonl`), events.join(''));
  save(`stage${stage}-sink.json`, { callback_ms: callbackMs, flush_ms: performance.now() - flushAt,
    bytes: Buffer.byteLength(events.join('')), events: events.length });
  save(`stage${stage}-ready.json`, { stage, pid: process.pid, pending: pending.length, closed: stage === 2,
    elapsed_ms: performance.now() - started });
  if (stage < 2) { await delay(60000); throw new Error('Controller did not kill fixed survivor stage'); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [runtimeDirectory, outputDirectory, stageText, baseURL] = process.argv.slice(2);
  await runWorker({ runtimeDirectory, outputDirectory, stage: Number(stageText), baseURL });
}
