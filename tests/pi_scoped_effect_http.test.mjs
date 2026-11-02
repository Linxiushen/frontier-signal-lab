// Real loopback Python/SQLite transport; the Harness host below is an in-memory test double.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import http from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createEffectClient, effectIdentity, openScopedGenerationService } from '../experiments/pi_scoped_effect_http_client.mjs';
import { makeEffectDispatcher } from '../experiments/pi_generation_http_service.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const item = (scope, payload = scope, key = '1:same-request') => effectIdentity({ key, payload, version: 1 }, 1, scope);

function host(client, identity, cancelled = false) {
  const state = { authority: { 1: { version: 1, allowed: true } },
    requests: { [identity.key]: { ...identity, requestId: identity.key.slice(2), cancelled } },
    effects: {}, effectIntents: { [identity.key]: { identity, status: 'pending' } } };
  const dispatcher = makeEffectDispatcher({ State: {}, context: {}, client, effectScope: identity.scope,
    harness: { snapshot: async () => structuredClone(state), commit: async callback => callback({ doc: async () => state }) } });
  return { state, dispatch: signal => dispatcher.dispatch(identity.key, signal) };
}

// Used only to check wire-level rejection and stop this test's owned process.
function raw(base, path, body, header = 'local-fixture-v2-scoped') {
  return new Promise((resolve, reject) => {
    const encoded = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    const req = http.request(new URL(path, base), { method: encoded ? 'POST' : 'GET', agent: false,
      headers: { 'x-frontier-fixture': header, ...(encoded ? { 'content-length': encoded.length } : {}) } }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks)) }));
    });
    req.setTimeout(2000, () => req.destroy(new Error('Test control timeout')));
    req.on('error', reject); req.end(encoded);
  });
}

async function startServer(t) {
  const directory = await mkdtemp(join(tmpdir(), 'frontier-scoped-effects-'));
  const executable = process.env.FRONTIER_TEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const child = spawn(executable, ['-X', 'utf8', '-B', '-S', 'experiments/pi_scoped_effect_http_server.py', '--output', directory, '--stage', '0'],
    { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = '', spawnError, base;
  child.stderr.on('data', chunk => { stderr += chunk; }); child.stdout.resume();
  child.on('error', error => { spawnError = error; });
  const exited = once(child, 'close').catch(() => []);
  t.after(async () => {
    try { if (base && child.exitCode === null) await raw(base, '/stop', {}); }
    finally {
      if (child.exitCode === null) {
        const stopped = await Promise.race([exited.then(() => true), delay(3000).then(() => false)]);
        if (!stopped) { child.kill(); await exited; }
      }
      await rm(directory, { recursive: true, force: true });
      assert.equal(child.exitCode, 0, `Owned fixture shutdown: ${stderr}`);
    }
  });
  const end = performance.now() + 8000;
  while (performance.now() < end) {
    if (spawnError) throw spawnError;
    if (child.exitCode !== null) throw new Error(`Fixture exited ${child.exitCode}: ${stderr}`);
    try { ({ base } = JSON.parse(await readFile(join(directory, 'effect-server0-ready.json'), 'utf8'))); break; }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    await delay(20);
  }
  assert.ok(base, `Fixture startup deadline: ${stderr}`);
  return { base, child, stderr: () => stderr };
}

test('scoped transport requires explicit scope and rejects foreign identities before I/O', async () => {
  for (const scope of [undefined, '', 'service/0', 'A', 'x'.repeat(65)])
    assert.throws(() => createEffectClient('http://127.0.0.1:1/', { scope }), /scope/);
  const client = createEffectClient('http://127.0.0.1:1/', { scope: 'service0' });
  await assert.rejects(client.apply(item('service1')), /Foreign effect scope/);
  await assert.rejects(client.request('GET', '/effects/service1/1%3Ar'), /Foreign effect scope/);
  await assert.rejects(client.request('POST', '/authority', { scope: 'service1' }), /Foreign effect scope/);
  await assert.rejects(client.request('POST', '/hold', { scope: 'service1' }), /Foreign effect scope/);
  await assert.rejects(openScopedGenerationService({ effectScope: 'service0', effectBase: 'http://127.0.0.1:1/', effectClient: client }), /constructs its own/);
});

test('two actual HTTP namespaces share a canonical key through the original dispatcher', { timeout: 15000 }, async t => {
  const server = await startServer(t);
  const clients = ['service0', 'service1'].map(scope => createEffectClient(server.base, { scope }));
  const [a, b] = clients;
  const authorize = (client, allowed, version = 1) => client.request('POST', '/authority', { scope: client.scope, conversation: 1, version, allowed });
  await authorize(a, true); await authorize(b, true);
  const identities = clients.map(client => item(client.scope));
  const hosts = clients.map((client, index) => host(client, identities[index]));
  assert.deepEqual(await Promise.all(hosts.map(h => h.dispatch())), ['commit', 'commit']);
  for (let index = 0; index < clients.length; index++) {
    const receipt = { ...identities[index], count: 1 };
    assert.deepEqual(await clients[index].lookup(identities[index]), receipt);
    assert.deepEqual(hosts[index].state.effects[identities[index].key].receipt, receipt);
    assert.equal((await clients[index].apply(identities[index])).created, false);
  }
  await assert.rejects(a.apply(item('service0', 'conflicting-payload')), /HTTP409/);
  await authorize(a, false, 2);
  assert.deepEqual(await a.apply(item('service0', 'new', '1:new')), { denied: true });
  assert.equal(await a.lookup(item('service0', 'new', '1:new')), undefined);
  const recovered = host(a, identities[0], true);
  recovered.state.authority[1] = { version: 2, allowed: false };
  assert.equal(await recovered.dispatch(), 'existing');
  assert.equal((await a.apply(identities[0])).created, false);
  let snapshot = (await a.request('GET', '/snapshot')).body;
  assert.deepEqual(snapshot.effects, identities.map(i => ({ ...i, count: 1 })));

  // Wire identity mismatches and v1 requests cannot mutate either namespace.
  assert.equal((await raw(server.base, '/effects/service0/1%3Aother', identities[0])).status, 400);
  assert.equal((await raw(server.base, '/effects/service0/1%3Asame-request', identities[1])).status, 400);
  assert.equal((await raw(server.base, '/effects/1%3Asame-request', identities[0])).status, 400);
  assert.equal((await raw(server.base, '/effects/service0/1%3Asame-request', identities[0], 'local-fixture-v1')).status, 400);
  assert.deepEqual((await a.request('GET', '/snapshot')).body.effects, snapshot.effects);

  await authorize(a, true);
  const opaque = item('service0', 'opaque', '1:path/with ?#雪');
  assert.equal((await a.apply(opaque)).created, true);
  assert.deepEqual(await a.lookup(opaque), { ...opaque, count: 1 });

  // Commit-before-lost-reply is a real HTTP event; host cancellation here is a test double.
  const held0 = item('service0', 'held', '1:held'), held1 = item('service1', 'free', '1:held');
  await a.request('POST', '/hold', { scope: 'service0', key: held0.key });
  const controller = new AbortController();
  const lost = a.apply(held0, controller.signal);
  const observed = lost.then(() => assert.fail('Held reply must not arrive'), error => error);
  const deadline = performance.now() + 1000;
  do {
    snapshot = (await a.request('GET', '/snapshot')).body;
    if (snapshot.effects.some(e => e.scope === 'service0' && e.key === held0.key)) break;
    await delay(10);
  } while (performance.now() < deadline);
  assert.ok(snapshot.effects.some(e => e.scope === 'service0' && e.key === held0.key));
  assert.equal((await b.apply(held1)).created, true); // Other scope is not held.
  controller.abort(new Error('test lost reply'));
  assert.match(String(await observed), /test lost reply/);
  assert.equal(await host(a, held0, true).dispatch(), 'existing');
  snapshot = (await a.request('GET', '/snapshot')).body;
  assert.equal(snapshot.effects.length, 5);
  assert.ok(snapshot.effects.every(e => e.count === 1));
  assert.equal(server.stderr(), '');
});

test('v2 real HTTP response identity, byte and wall bounds remain enforced', async t => {
  const identity = item('service0');
  const server = http.createServer((req, res) => {
    if (req.url.includes('slow')) return;
    res.end(req.url.includes('large') ? 'x'.repeat(17000) : req.url.includes('malformed') ? '{' : JSON.stringify({ ...identity, scope: 'service1', count: 1 }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const client = createEffectClient(`http://127.0.0.1:${server.address().port}/`, { scope: 'service0', timeoutMs: 150 });
  await assert.rejects(client.lookup(identity), /Foreign effect receipt/);
  await assert.rejects(client.request('GET', '/effects/service0/malformed'), SyntaxError);
  await assert.rejects(client.request('GET', '/effects/service0/large'), /byte ceiling/);
  await assert.rejects(client.request('GET', '/effects/service0/slow'), /wall deadline/);
});
