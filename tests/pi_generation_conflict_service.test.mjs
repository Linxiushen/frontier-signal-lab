import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateSubmissionIdentity, reservationAction, effectDecision, quarantineConflict } from '../experiments/pi_generation_conflict_service.mjs';
import { payloadFingerprint } from '../experiments/pi_durable_service_v2.mjs';
import { openGenerationService } from '../experiments/pi_generation_conflict_service.mjs';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
const request = { conversation: 'c', requestId: 'r', payload: 'p', version: 3, fingerprint: payloadFingerprint('p') };
const native = { id: 'n', type: 'input', conversationId: 'c', requestId: 'r' };
const entry = { kind: 'pi.user', conversationId: 'c', model: [{ role: 'user', content: JSON.stringify({ key: 'c:r', payload: 'p', version: 3 }) }] };
test('recover the exact original submission identity and content', () => {
  validateSubmissionIdentity(request, native, entry);
  for (const change of [{ type: 'write' }, { conversationId: 'other' }, { requestId: 'other' }])
    assert.throws(() => validateSubmissionIdentity(request, { ...native, ...change }, entry), /mismatch/);
});
test('same request ID cannot import changed payload or argument version', () => {
  for (const content of ['changed', JSON.stringify({ key: 'c:r', payload: 'q', version: 3 }), JSON.stringify({ key: 'c:r', payload: 'p', version: 4 })])
    assert.throws(() => validateSubmissionIdentity(request, native, { ...entry, model: [{ role: 'user', content }] }), /mismatch/);
  for (const changed of [undefined, { ...entry, kind: 'other' }, { ...entry, conversationId: 'other' }, { ...entry, model: [] }])
    assert.throws(() => validateSubmissionIdentity(request, native, changed), /mismatch/);
});
test('pending reservation rechecks current permission and durable cancellation', () => {
  const state = { authority: { c: { allowed: true, version: 3 } } };
  assert.equal(reservationAction(state, request), 'submit');
  state.authority.c.version = 4; assert.equal(reservationAction(state, request), 'denied-before-submit');
  state.authority.c = { allowed: false, version: 3 }; assert.equal(reservationAction(state, request), 'denied-before-submit');
  assert.equal(reservationAction({ authority: {} }, request), 'denied-before-submit');
  assert.equal(reservationAction(state, { ...request, cancelled: true }), 'cancelled-before-submit');
});
test('cancel mark survives signal loss and blocks even an existing local effect replay', () => {
  const state = { authority: { c: { allowed: true, version: 3 } }, requests: { 'c:r': { ...request, cancelled: true } }, effects: { 'c:r': { count: 1, payload: 'p' } } };
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'aborted');
  state.requests['c:r'].cancelled = false;
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'existing');
  state.authority.c.allowed = false;
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'denied');
});

// This fixture checks the actual adapter method against a fake Harness. It opens
// no native runtime/SQLite, schedules no model work, and proves no crash recovery.
async function mockedService(t, cancellationGate, mismatch = false) {
  const root = mkdtempSync(join(tmpdir(), 'frontier-cancel-unit-'));
  t.after(() => {
    assert.equal(dirname(resolve(root)), resolve(tmpdir()));
    assert.ok(root.split(/[\\/]/).at(-1).startsWith('frontier-cancel-unit-'));
    rmSync(root, { recursive: true }); delete globalThis.__frontierCancelUnitHarness;
  });
  const write = (name, text) => {
    const path = join(root, 'node_modules/@earendil-works', name);
    mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, text);
  };
  for (const name of ['pi-durable', 'pi-ai', 'chord']) write(`${name}/package.json`, '{"type":"module"}');
  write('pi-durable/dist/index.js', `
    export const Harness={open:async()=>globalThis.__frontierCancelUnitHarness};
    export const createRegistry=()=>({install(){}});
    export const defineDoc=x=>x, defineTool=x=>x;`);
  write('pi-durable/dist/storage/sqlite/node.js', 'export const openNodeSqliteStorage=async x=>x;');
  write('chord/dist/context/index.js', 'export const BACKGROUND_CONTEXT={value(){},telemetry:{}};');
  write('pi-ai/dist/index.js', `
    export const Type={Object:x=>x,String:()=>({}),Integer:()=>({})};
    export const createModels=()=>({setProvider(){}});
    export const fauxProvider=()=>({getModel:()=>({api:'fake',provider:'fake',id:'fake'}),setResponses(){},provider:{}});
    export const fauxAssistantMessage=()=>{},fauxToolCall=()=>{};`);
  const state = { authority: { c: { allowed: true, version: 3 } },
    requests: { 'c:r': { ...request, submissionId: 'n' } }, active: { 'c:r': true }, effects: {} };
  const record = { ...native, ...(mismatch ? { type: 'write' } : {}), entry: 'e', status: 'placed' };
  let aborts = 0;
  const harness = { subscribeCommits(){}, snapshot: async () => structuredClone(state),
    commit: async callback => callback({ doc: async () => state,
      submissionByRequest: async () => record, entry: async () => entry }),
    conversation: async () => ({ abort: async () => { aborts++; record.status = 'unanswered'; } }) };
  globalThis.__frontierCancelUnitHarness = harness;
  const service = await openGenerationService({ runtimeDirectory: root, database: 'not-a-database',
    phaseGate: async () => {}, emit: () => {}, cancellationGate });
  return { service, state, aborts: () => aborts };
}

test('actual adapter checkpoint observes committed cancel mark before any native abort', async t => {
  let fixture;
  fixture = await mockedService(t, async (phase, key) => {
    assert.equal(phase, 'after-cancel-mark'); assert.equal(key, 'c:r');
    assert.equal(fixture.state.requests[key].cancelled, true);
    assert.equal(fixture.aborts(), 0); throw new Error('Injected checkpoint loss');
  });
  await assert.rejects(fixture.service.cancelRequest('c', 'r'), /Injected checkpoint loss/);
  assert.equal(fixture.state.requests['c:r'].cancelled, true);
  assert.equal(fixture.aborts(), 0);
});

test('optional checkpoint default retains native abort and exact link reconciliation', async t => {
  const fixture = await mockedService(t, undefined);
  await fixture.service.cancelRequest('c', 'r');
  assert.equal(fixture.aborts(), 1);
  assert.equal(fixture.state.requests['c:r'].cancelled, true);
  assert.equal(fixture.state.requests['c:r'].submissionId, 'n');
});

test('unknown reservation reaches neither checkpoint nor native abort', async t => {
  let checkpoints = 0;
  const fixture = await mockedService(t, async () => { checkpoints++; });
  await assert.rejects(fixture.service.cancelRequest('c', 'missing'), /Unknown durable request/);
  assert.equal(checkpoints, 0); assert.equal(fixture.aborts(), 0);
});

test('collision retires only host capacity and preserves exact foreign record', () => {
  for (const changed of [{ ...native, type: 'write' }, native]) {
    const state = { requests: { 'c:r': { ...request, cancelled: true } }, active: { 'c:r': true }, effects: {} };
    const original = structuredClone(changed);
    const result = quarantineConflict(state, 'c:r', changed, { ...entry, model: [{ role: 'user', content: 'other' }] });
    assert.deepEqual(changed, original);
    assert.deepEqual(state.active, {});
    assert.equal(state.requests['c:r'].cancelled, true);
    assert.equal(result.status, 'native-conflict');
    assert.equal(result.nativeSubmissionId, 'n');
    assert.equal(state.requests['c:r'].submissionId, undefined);
  }
});
test('matching original reservation remains active; invalid host address is rejected', () => {
  const state = { requests: { 'c:r': { ...request } }, active: { 'c:r': true } };
  const before = structuredClone(state);
  assert.equal(quarantineConflict(state, 'c:r', native, entry), undefined);
  assert.deepEqual(state, before);
  assert.throws(() => quarantineConflict(state, 'missing', native, entry), /exact active/);
});
test('actual cancellation method refuses a foreign native identity before abort', async t => {
  const fixture = await mockedService(t, undefined, true);
  await fixture.service.cancelRequest('c', 'r');
  assert.equal(fixture.aborts(), 0);
  assert.equal(fixture.state.requests['c:r'].cancelled, true);
  assert.equal(fixture.state.requests['c:r'].terminal.status, 'native-conflict');
  assert.deepEqual(fixture.state.active, {});
});

test('quarantined semantically equivalent foreign JSON cannot commit an effect', () => {
  const state = { authority: { c: { allowed: true, version: 3 } },
    requests: { 'c:r': { ...request } }, active: { 'c:r': true }, effects: {} };
  // Byte identity differs while the model-parsed tool arguments are identical.
  const foreign = { ...entry, model: [{ role: 'user', content: ' { "key": "c:r", "payload": "p", "version": 3 } ' }] };
  quarantineConflict(state, 'c:r', native, foreign);
  assert.equal(effectDecision(state, { key: 'c:r', payload: 'p', version: 3 }, 'c', false), 'conflict');
  assert.deepEqual(state.effects, {});
});
