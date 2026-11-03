// Actual dispatcher with controlled host/transport doubles; no native runtime.
import assert from 'node:assert/strict';
import test from 'node:test';
import { makeReceiptDispatcher } from '../experiments/pi_generation_receipt_service.mjs';
import { effectIdentity } from '../experiments/pi_effect_http_client.mjs';

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}
function fixture(client) {
  const identity = effectIdentity({ key: 'c:r', payload: 'value', version: 1 }, 'c');
  const receipt = { ...identity, count: 1 }, events = [];
  const state = { authority: { c: { version: 1, allowed: true } },
    requests: { 'c:r': { ...identity, requestId: 'r' } }, effects: {},
    effectIntents: { 'c:r': { identity, status: 'pending' } } };
  const dispatcher = makeReceiptDispatcher({ State: {}, context: {}, client, emit: e => events.push(e),
    harness: { snapshot: async () => structuredClone(state), commit: async fn => fn({ doc: async () => state }) } });
  return { identity, receipt, state, events, dispatch: signal => dispatcher.dispatch('c:r', signal) };
}
function overlapping() {
  const applyEntered = deferred(), lookupEntered = deferred(), applyReply = deferred(), lookupReply = deferred();
  let lookups = 0;
  const f = fixture({ lookup: async () => {
    if (++lookups === 1) return undefined;
    lookupEntered.resolve(); return lookupReply.promise;
  }, apply: async () => { applyEntered.resolve(); return applyReply.promise; } });
  return { ...f, applyEntered, lookupEntered, applyReply, lookupReply };
}
function committed(f) {
  assert.equal(f.state.effectIntents['c:r'].status, 'committed');
  assert.deepEqual(f.state.effectIntents['c:r'].receipt, f.receipt);
  assert.deepEqual(f.state.effects['c:r'], { count: 1, payload: 'value', receipt: f.receipt });
}

test('late missing lookup cannot overwrite acknowledged receipt after cancel or host revoke', async t => {
  for (const reason of ['cancel', 'host-revoke', 'signal-abort']) await t.test(reason, async () => {
    const f = overlapping(), controller = new AbortController();
    const first = f.dispatch(); await f.applyEntered.promise;
    const late = f.dispatch(controller.signal); await f.lookupEntered.promise;
    if (reason === 'cancel') f.state.requests['c:r'].cancelled = true;
    if (reason === 'host-revoke') f.state.authority.c.allowed = false;
    if (reason === 'signal-abort') controller.abort();
    f.applyReply.resolve({ created: true, receipt: f.receipt });
    assert.equal(await first, 'commit'); committed(f);
    f.lookupReply.resolve(undefined);
    assert.equal(await late, 'existing'); committed(f);
    assert.equal(f.state.requests['c:r'].effectDenied, undefined);
    assert.equal(f.events.filter(e => e.type === 'effect-refused').length, 0);
    assert.equal(f.events.filter(e => e.type === 'effect-disposition-superseded').length, 1);
  });
});

test('delayed remote refusal cannot replace a receipt acknowledged by another callback', async () => {
  const entered = [deferred(), deferred()], replies = [deferred(), deferred()];
  let applies = 0;
  const f = fixture({ lookup: async () => undefined, apply: async () => {
    const i = applies++; entered[i].resolve(); return replies[i].promise;
  } });
  const first = f.dispatch(); await entered[0].promise;
  const late = f.dispatch(); await entered[1].promise;
  replies[0].resolve({ created: true, receipt: f.receipt }); assert.equal(await first, 'commit');
  replies[1].resolve({ denied: true }); assert.equal(await late, 'existing'); committed(f);
  assert.equal(f.state.requests['c:r'].effectDenied, undefined);
  assert.equal(f.events.filter(e => e.type === 'effect-refused').length, 0);
});

test('refusal before acknowledgement still permits the original historical receipt', async () => {
  const f = overlapping();
  const first = f.dispatch(); await f.applyEntered.promise;
  const late = f.dispatch(); await f.lookupEntered.promise;
  f.state.requests['c:r'].cancelled = true;
  f.lookupReply.resolve(undefined); assert.equal(await late, 'aborted');
  f.applyReply.resolve({ created: true, receipt: f.receipt });
  assert.equal(await first, 'commit'); committed(f);
});

test('superseded disposition still rejects changed host identity and invalid saved receipts', async t => {
  for (const mutation of ['host', 'intent-receipt', 'effect-receipt']) await t.test(mutation, async () => {
    const f = overlapping();
    const first = f.dispatch(); await f.applyEntered.promise;
    const late = f.dispatch(); const rejected = assert.rejects(late, /identity|Foreign effect receipt/);
    await f.lookupEntered.promise;
    f.applyReply.resolve({ created: true, receipt: f.receipt }); await first;
    if (mutation === 'host') f.state.requests['c:r'].payload = 'changed';
    if (mutation === 'intent-receipt') f.state.effectIntents['c:r'].receipt = { ...f.receipt, payload: 'foreign' };
    if (mutation === 'effect-receipt') f.state.effects['c:r'].receipt = { ...f.receipt, count: 2 };
    f.state.requests['c:r'].cancelled = true;
    f.lookupReply.resolve(undefined); await rejected;
    assert.equal(f.state.effectIntents['c:r'].status, 'committed');
    assert.equal(f.events.filter(e => e.type === 'effect-disposition-superseded').length, 0);
  });
});

test('ordinary refusal, unknown reply and foreign response retain separate outcomes', async () => {
  const denied = fixture({ lookup: async () => undefined, apply: async () => ({ denied: true }) });
  assert.equal(await denied.dispatch(), 'denied'); assert.equal(denied.state.requests['c:r'].effectDenied, true);
  assert.deepEqual(denied.state.effects, {});
  const unknown = fixture({ lookup: async () => undefined, apply: async () => { throw new Error('lost reply'); } });
  await assert.rejects(unknown.dispatch(), /lost reply/);
  assert.equal(unknown.state.effectIntents['c:r'].status, 'pending'); assert.deepEqual(unknown.state.effects, {});
  const foreign = fixture({ lookup: async () => ({ ...unknown.receipt, scope: 'foreign' }) });
  await assert.rejects(foreign.dispatch(), /Foreign effect receipt/);
  assert.equal(foreign.state.effectIntents['c:r'].status, 'pending'); assert.deepEqual(foreign.state.effects, {});
});
