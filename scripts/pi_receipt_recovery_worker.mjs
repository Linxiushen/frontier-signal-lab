// Actual paused Harness recovery caller for the opt-in receipt-monotonic service.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { openReceiptGenerationService } from '../experiments/pi_generation_receipt_service.mjs';
import { createEffectClient, effectIdentity } from '../experiments/pi_scoped_effect_http_client.mjs';
import { createRecoveryClient } from '../experiments/pi_receipt_recovery_barriers.mjs';
import { createTransportGate } from './pi_generation_http_worker.mjs';

export async function runWorker({ runtimeDirectory, outputDirectory, stage, baseURL }) {
  assert.ok(Number.isInteger(stage) && [0, 1, 2].includes(stage));
  const output = resolve(outputDirectory), started = performance.now();
  const events = [], services = [], clients = [], released = new Set(), cancelHolds = new Set(), marked = new Set();
  const raceReleased = new Set(), raceHeld = new Set(), errors = [], cancellations = [];
  let callbackMs = 0;
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
  const flush = () => {
    const at = performance.now(), text = events.join(''); writeFileSync(resolve(output, `stage${stage}.jsonl`), text);
    save(`stage${stage}-sink.json`, { callback_ms: callbackMs, flush_ms: performance.now() - at, bytes: Buffer.byteLength(text), events: events.length });
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
  try {
    const control = createEffectClient(baseURL, { scope: 'service0', emit: e => emit({ service: -1, ...e }) });
    const remoteSnapshot = async () => {
      const r = await control.request('GET', '/snapshot'); assert.equal(r.status, 200); return r.body;
    };
    const initial = await remoteSnapshot(); save(`effect-server${stage}-initial-snapshot.json`, initial);
    if (stage) assert.deepEqual(initial, JSON.parse(readFileSync(resolve(output, `effect-server${stage - 1}-final.json`), 'utf8')));
    assert.equal(initial.effects.length, [0, 0, 4][stage]);
    const ids = stage ? JSON.parse(readFileSync(resolve(output, 'identities.json'), 'utf8')) :
      { conversations: [[], []], requests: [], recovered: [], retries: [], conflicts: [] };
    for (let s = 0; s < 2; s++) {
      const scope = `service${s}`;
      const client = createEffectClient(baseURL, { scope, emit: e => emit({ service: s, ...e }) });
      clients.push(client);
      const race = stage === 1 ? ids.requests.find(r => r.service === s && r.intent === 'race') : undefined;
      const wrapped = race ? createRecoveryClient({ client, key: race.key, mode: s ? 'late-refusal' : 'late-missing',
        emit: e => emit({ service: s, ...e }), hold: async label => {
          const q = `${s}:${label}`; raceHeld.add(q); emit({ type: 'race-held', service: s, key: race.key, label });
          await wait(() => raceReleased.has(q)); emit({ type: 'race-released', service: s, key: race.key, label });
        } }) : client;
      const service = await openReceiptGenerationService({ runtimeDirectory, effectClient: wrapped, effectScope: scope,
        database: resolve(output, `service${s}.sqlite`), providerApi: s ? 'frontier-faux-receipts' : undefined,
        phaseGate: createTransportGate({ service: s, released, emit }),
        cancellationGate: async (phase, key) => {
          const q = `${s}:${key}`;
          if (!cancelHolds.has(q)) return;
          assert.equal(phase, 'after-cancel-mark'); marked.add(q); emit({ type: 'cancel-mark-held', service: s, key });
          await wait(() => !cancelHolds.has(q));
          emit({ type: 'cancel-mark-released', service: s, key });
        }, emit: e => emit({ service: s, ...e }) });
      services.push(service);
      if (!stage) for (let c = 0; c < 2; c++) ids.conversations[s].push(await service.createConversation());
    }
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
    async function remoteAuthorize(s, c, version, allowed) {
      const body = { scope: `service${s}`, conversation: ids.conversations[s][c], version, allowed };
      const r = await clients[s].request('POST', '/authority', body); assert.equal(r.status, 200);
      emit({ type: 'remote-authority', ...body });
    }
    async function markHold(r) {
      cancelHolds.add(qualified(r));
      const promise = services[r.service].cancelRequest(r.conversation, r.requestId);
      cancellations.push(promise); promise.catch(error => errors.push(error));
      await wait(() => marked.has(qualified(r)));
      assert.equal((await services[r.service].snapshot()).requests[r.key].cancelled, true);
    }
    if (stage) {
      const pending = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
      assert.equal(pending.length, 4);
      for (const r of pending) emit({ type: 'recovery-before-resume', service: r.service, key: r.key, state: await services[r.service].snapshot() });
      if (stage === 1) {
        // Both callers use the public recovery entrypoint on the same paused
        // owner. Each response is genuine; only callback delivery is scheduled.
        for (let s = 0; s < 2; s++) {
          const service = services[s], r = pending.find(r => r.service === s && r.intent === 'race');
          const call = label => {
            emit({ type: 'reconcile-start', service: s, key: r.key, label });
            const p = service.reconcile().then(() => emit({ type: 'reconcile-finish', service: s, key: r.key, label }));
            p.catch(error => errors.push(error)); return p;
          };
          const first = call('first'); await wait(() => raceHeld.has(`${s}:first-apply`));
          // Existing remote receipts take precedence over current authority. To
          // obtain a genuine refusal, observe it BEFORE the first real create,
          // hold its callback, then restore authority for that first create.
          if (s === 1) await remoteAuthorize(s, 0, r.version, false);
          const second = call('second'); await wait(() => raceHeld.has(`${s}:${s ? 'late-refusal' : 'late-missing'}`));
          if (s === 1) await remoteAuthorize(s, 0, r.version, true);
          raceReleased.add(`${s}:first-apply`); await first;
          const committed = await service.snapshot();
          assert.equal(committed.effectIntents[r.key].status, 'committed');
          assert.deepEqual(committed.effectIntents[r.key].receipt, { ...effectIdentity(r, r.conversation, r.scope), count: 1 });
          save(`race${s}-acknowledged.json`, committed);
          emit({ type: 'race-first-acknowledged', service: s, key: r.key, state: committed });
          if (s === 0) {
            await service.authorize(r.conversation, r.version, false);
            emit({ type: 'host-authority-withdrawn', service: s, key: r.key, conversation: r.conversation, version: r.version });
          } else await remoteAuthorize(s, 0, r.version, false);
          raceReleased.add(`${s}:${s ? 'late-refusal' : 'late-missing'}`); await second;
          const after = await service.snapshot();
          assert.equal(after.effectIntents[r.key].status, 'committed');
          assert.deepEqual(after.effectIntents[r.key].receipt, committed.effectIntents[r.key].receipt);
          assert.deepEqual(after.effects[r.key], committed.effects[r.key]); assert.equal(after.requests[r.key].effectDenied, undefined);
          assert.equal(ownEvents('effect-disposition-superseded', r).length, 1);
          assert.equal((await service.harness.inspect(service.context)).scheduling, 'paused');
          save(`race${s}-preserved.json`, after); emit({ type: 'race-receipt-preserved', service: s, key: r.key, state: after });
        }
        for (const r of pending.filter(r => r.intent === 'race')) await markHold(r);
      } else {
        for (const r of pending) released.add(qualified(r));
        for (const service of services) await service.reconcile();
        for (const service of services) service.harness.resume();
        await wait(async () => { await reap(); return pending.every(r => r.terminal); });
        save('stage2-recovered.json', { states: await Promise.all(services.map(s => s.snapshot())), server: await remoteSnapshot() });
      }
      for (const r of pending) ids.recovered.push({ stage, service: r.service, key: r.key, submissionId: r.submissionId });
    }
    if (stage !== 1) {
      const version = stage === 0 ? 1 : 2;
      for (let s = 0; s < 2; s++) for (let c = 0; c < 2; c++) {
        await services[s].authorize(ids.conversations[s][c], version, true); await remoteAuthorize(s, c, version, true);
      }
      function request(s, c, intent) {
        const requestId = `s${stage}-${intent}`, conversation = ids.conversations[s][c];
        const r = { stage, service: s, scope: `service${s}`, conversation, requestId, intent, version,
          key: `${conversation}:${requestId}`, payload: `service${s}/${requestId}`, offered_epoch_ms: Date.now() };
        ids.requests.push(r); return r;
      }
      async function admit(r) {
        Object.assign(r, await services[r.service].admit(r.conversation, r.requestId, r.payload, r.version));
        assert.equal(r.status, r.intent === 'overload' ? 'overloaded' : 'admit');
        if (r.status === 'admit') assert.ok(Number.isSafeInteger(r.submissionId) && r.submissionId > 0);
        return r;
      }
      const current = [];
      for (let s = 0; s < 2; s++) {
        current.push(await admit(request(s, 0, stage === 0 ? 'race' : 'negative')));
        current.push(await admit(request(s, 1, 'positive')));
        await admit(request(s, 0, 'overload'));
      }
      for (const r of current) {
        await wait(async () => ownEvents('transport-held', r).length === 1 &&
          (await services[r.service].snapshot()).effectIntents[r.key]?.status === 'pending');
        assert.deepEqual((await services[r.service].snapshot()).effectIntents[r.key].identity, effectIdentity(r, r.conversation, r.scope));
      }
      if (stage === 2) {
        const denied = current.find(r => r.service === 0 && r.intent === 'negative');
        await services[0].authorize(denied.conversation, denied.version, false);
        emit({ type: 'host-authority-withdrawn', service: 0, key: denied.key, conversation: denied.conversation, version: denied.version });
        const cancelled = current.find(r => r.service === 1 && r.intent === 'negative'); await markHold(cancelled);
        for (const r of current) released.add(qualified(r));
        await wait(async () => { await reap(); return current.every(r => r.terminal); });
        cancelHolds.delete(qualified(cancelled)); await Promise.all(cancellations);
        for (const r of current.filter(r => r.intent === 'positive')) {
          const retry = await services[r.service].admit(r.conversation, r.requestId, r.payload, r.version);
          assert.equal(retry.status, 'duplicate'); assert.equal(retry.submissionId, r.submissionId);
          ids.retries.push({ service: r.service, key: r.key, ...retry });
          const conflict = await services[r.service].admit(r.conversation, r.requestId, `changed/${r.payload}`, r.version);
          assert.equal(conflict.status, 'conflict'); ids.conflicts.push({ service: r.service, key: r.key, ...conflict });
        }
      }
    }
    const states = await Promise.all(services.map(s => s.snapshot()));
    for (const service of services) service.flush();
    const pending = ids.requests.filter(r => r.status === 'admit' && !r.terminal);
    assert.equal(pending.length, [4, 4, 0][stage]);
    const server = await remoteSnapshot(); assert.equal(server.effects.length, [0, 4, 6][stage]);
    save('identities.json', ids); save(`stage${stage}-snapshot.json`, { stage, pid: process.pid, states, pending, server });
    if (stage === 2) for (const service of services) { await service.harness.waitForIdle(service.context); await service.close(); service.flush(); }
    assert.equal(events.map(JSON.parse).filter(e => ['network-access-denied', 'runtime-report'].includes(e.type)).length, 0);
    if (errors.length) throw errors[0]; emit({ type: 'ready', pending: pending.length }); flush();
    save(`stage${stage}-ready.json`, { stage, pid: process.pid, pending: pending.length, closed: stage === 2, elapsed_ms: performance.now() - started });
    if (stage < 2) { await delay(60000); throw new Error('Controller did not kill fixed survivor stage'); }
  } catch (error) {
    save(`stage${stage}-failure.json`, { error: String(error), stack: error.stack, elapsed_ms: performance.now() - started });
    flush(); throw error;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [runtimeDirectory, outputDirectory, stageText, baseURL] = process.argv.slice(2);
  await runWorker({ runtimeDirectory, outputDirectory, stage: Number(stageText), baseURL });
}
