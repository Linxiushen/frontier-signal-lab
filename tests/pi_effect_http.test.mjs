import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { createEffectClient, effectIdentity, validateEffectReceipt } from '../experiments/pi_effect_http_client.mjs';
import { makeEffectDispatcher } from '../experiments/pi_generation_http_service.mjs';

const identity = effectIdentity({ key: 'c:r', payload: 'value', version: 1 }, 'c');
function fixture(client, cancelled = false) {
  const state = { authority: { c: { version: 1, allowed: true } },
    requests: { 'c:r': { conversation: 'c', requestId: 'r', payload: 'value', fingerprint: identity.fingerprint, version: 1, cancelled } },
    effects: {}, effectIntents: { 'c:r': { identity, status: 'pending' } } };
  return { state, dispatch: makeEffectDispatcher({ State: {}, context: {}, client,
    harness: { snapshot: async () => structuredClone(state), commit: async callback => callback({ doc: async () => state }) } }).dispatch };
}
test('newly created remote effect preserves native commit result and exact receipt', async () => {
  const acknowledged = { ...identity, count: 1 };
  let applied = 0;
  const f = fixture({ lookup: async () => undefined, apply: async original => {
    assert.deepEqual(original, identity); applied++;
    return { created: true, receipt: acknowledged };
  } });
  assert.equal(await f.dispatch('c:r'), 'commit');
  assert.equal(applied, 1);
  assert.deepEqual(f.state.effects['c:r'], { payload: 'value', count: 1, receipt: acknowledged });
  assert.equal(f.state.effectIntents['c:r'].status, 'committed');
});
test('unknown reply recovers existing receipt after cancellation without applying', async () => {
  let applied = 0;
  const f = fixture({ lookup: async () => ({ ...identity, count: 1 }), apply: async () => { applied++; } }, true);
  assert.equal(await f.dispatch('c:r'), 'existing');
  assert.equal(applied, 0); assert.equal(f.state.effects['c:r'].count, 1);
  assert.equal(f.state.effectIntents['c:r'].status, 'committed');
});
test('cancelled missing effect and current authority denial never apply', async () => {
  for (const cancelled of [true, false]) {
    const f = fixture({ lookup: async () => undefined, apply: async () => assert.fail('No mutation allowed') }, cancelled);
    f.state.authority.c.allowed = false;
    assert.equal(await f.dispatch('c:r'), cancelled ? 'aborted' : 'denied');
    assert.deepEqual(f.state.effects, {});
  }
});
test('remote authority refusal and unknown transport reply retain distinct states', async () => {
  const refused = fixture({ lookup: async () => undefined, apply: async () => ({ denied: true }) });
  assert.equal(await refused.dispatch('c:r'), 'denied'); assert.equal(refused.state.requests['c:r'].effectDenied, true);
  const unknown = fixture({ lookup: async () => undefined, apply: async () => { throw new Error('lost reply'); } });
  await assert.rejects(unknown.dispatch('c:r'), /lost reply/);
  assert.equal(unknown.state.effectIntents['c:r'].status, 'pending'); assert.deepEqual(unknown.state.effects, {});
});
test('foreign receipt cannot acknowledge a durable intent', async () => {
  const f = fixture({ lookup: async () => ({ ...identity, payload: 'foreign', count: 1 }) });
  await assert.rejects(f.dispatch('c:r'), /Foreign effect receipt/); assert.deepEqual(f.state.effects, {});
  assert.throws(() => validateEffectReceipt(identity, { ...identity, count: 2 }));
});
test('changed host identity refuses even receipt observation', async () => {
  const f = fixture({ lookup: async () => assert.fail('Changed host cannot dispatch') });
  f.state.requests['c:r'].payload = 'changed';
  await assert.rejects(f.dispatch('c:r'), /no longer matches host identity/);
});
test('transport requires exact loopback destination', () => {
  for (const base of ['https://127.0.0.1:1234/', 'http://localhost:1234/', 'http://example.com/', 'http://127.0.0.1:1234/path', 'http://u@127.0.0.1:1234/'])
    assert.throws(() => createEffectClient(base));
});
test('remote identities preserve numeric native IDs and distinguish Session scope', async () => {
  const native = { key: '2:request', payload: 'value', version: 1 };
  const a = effectIdentity(native, 2, 'service0'), b = effectIdentity(native, 2, 'service1');
  assert.equal(a.conversation, 2); assert.notDeepEqual(a, b);
  assert.throws(() => effectIdentity(native, true, 'service0'));
  assert.throws(() => validateEffectReceipt(a, { ...b, count: 1 }));
  const f = fixture({ lookup: async () => assert.fail('Wrong scope must not observe or mutate') });
  f.state.effectIntents['c:r'].identity.scope = 'foreign';
  await assert.rejects(f.dispatch('c:r'), /no longer matches host identity/);
});
test('real loopback HTTP accepts exact reply; malformed/large/slow replies are bounded', async t => {
  const server = http.createServer((req, res) => {
    if (req.url.includes('slow')) return;
    res.end(req.url.includes('large') ? 'x'.repeat(17000) : req.url.includes('malformed') ? '{' : JSON.stringify({ ...identity, count: 1 }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const client = createEffectClient(`http://127.0.0.1:${server.address().port}/`, { timeoutMs: 100 });
  assert.deepEqual(await client.lookup(identity), { ...identity, count: 1 });
  await assert.rejects(client.request('GET', '/effects/malformed'), SyntaxError);
  await assert.rejects(client.request('GET', '/effects/large'), /byte ceiling/);
  await assert.rejects(client.request('GET', '/effects/slow'), /wall deadline/);
});
