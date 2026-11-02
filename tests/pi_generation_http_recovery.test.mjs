// Pure public-API boundary controls; no optional runtime, native DB or HTTP server.
import test from 'node:test';
import assert from 'node:assert/strict';
import { effectFingerprint } from '../experiments/pi_effect_http_client.mjs';
import { preparePausedRecoveryAborts } from '../experiments/pi_generation_http_service.mjs';

function fixture() {
  const state = { requests: {}, active: {} }, tasks = [], submissions = [], entries = [], calls = [], events = [];
  for (let c = 0; c < 2; c++) {
    const conversation = 2 + c * 6, requestId = `request-${c}`, key = `${conversation}:${requestId}`;
    const payload = `payload-${c}`, args = { key, payload, version: 1 };
    const generation = 5 + c * 6, tool = 7 + c * 6, user = 4 + c * 6, assistant = 6 + c * 6;
    const callId = `call-${effectFingerprint(key).slice(0, 24)}`;
    state.requests[key] = { conversation, requestId, payload, version: 1, fingerprint: effectFingerprint(payload),
      ...(c ? { effectDenied: true } : { cancelled: true }) };
    state.active[key] = true;
    entries.push({ id: user, kind: 'pi.user', conversationId: conversation,
      model: [{ role: 'user', content: JSON.stringify(args) }] });
    entries.push({ id: assistant, kind: 'pi.assistant', conversationId: conversation, byTaskId: generation,
      model: [{ role: 'assistant', content: [{ type: 'toolCall', id: callId, name: 'frontier_effect', arguments: args }] }] });
    submissions.push({ id: 3 + c * 6, type: 'input', status: 'placed', conversationId: conversation, requestId, entry: user });
    tasks.push({ id: generation, kind: 'pi.generation', version: 1, conversationId: conversation, background: false, input: {},
      state: { status: 'waiting', on: [tool], policy: 'allSettled',
        checkpoint: { phase: 'tools', assistant, tools: [tool], pending: [] } } });
    tasks.push({ id: tool, kind: 'pi.tool', version: 2, conversationId: conversation, background: false, owner: generation,
      input: { kind: 'model', assistant, callId },
      state: { status: 'pending', checkpoint: { phase: 'execute', arguments: args, replay: 'safe' } } });
  }
  const controls = { scheduling: 'paused', mark: true };
  const copy = value => structuredClone(value);
  const harness = {
    async inspect() {
      calls.push({ type: 'inspect', scheduling: controls.scheduling });
      return { scheduling: controls.scheduling, tasks: tasks.map(record => ({ record: copy(record), state: { kind: 'ready' } })),
        submissions: copy(submissions) };
    },
    async commit(change) {
      calls.push({ type: 'preflight-start' });
      const result = await change({
        async doc() { return state; },
        async submissionByRequest(conversation, requestId) { return copy(submissions.find(s => s.conversationId === conversation && s.requestId === requestId)); },
        async entry(id) { calls.push({ type: 'entry-read', id }); return copy(entries.find(e => e.id === id)); },
        async task(id) { calls.push({ type: 'task-read', id }); return copy(tasks.find(t => t.id === id)); },
      });
      calls.push({ type: 'preflight-end' }); return result;
    },
    async abortTask(id) {
      calls.push({ type: 'abortTask', id, scheduling: controls.scheduling });
      if (controls.mark) tasks.find(t => t.id === id).abortRequested = true;
      if (controls.resumeAfterMark) controls.scheduling = 'running';
      return 'marked';
    },
  };
  return { state, tasks, submissions, entries, calls, events, controls, harness,
    run: () => preparePausedRecoveryAborts({ harness, State: 'state-token', context: 'context', emit: e => events.push(e) }) };
}

test('both exact placed chains are validated and fully marked before any native progress', async () => {
  const f = fixture(), plans = await f.run();
  assert.equal(plans.length, 2);
  assert.deepEqual(f.calls.filter(c => c.type === 'abortTask').map(c => c.id),
    [5, 7, 11, 13]);
  assert.ok(f.calls.filter(c => c.type === 'inspect').every(c => c.scheduling === 'paused'));
  assert.ok(f.calls.filter(c => c.type === 'abortTask').every(c => c.scheduling === 'paused'));
  assert.ok(f.calls.findIndex(c => c.type === 'abortTask') > f.calls.findIndex(c => c.type === 'preflight-end'));
  assert.ok(f.tasks.every(t => t.abortRequested));
  assert.deepEqual(f.events, plans.map(p => ({ type: 'recovery-native-preabort', ...p, scheduling: 'paused' })));
});

test('a foreign native request is quarantined without marking its tasks', async () => {
  const f = fixture();
  f.entries[0].model[0].content = JSON.stringify({ key: 'foreign', payload: 'foreign', version: 1 });
  const plans = await f.run();
  assert.deepEqual(plans.map(p => p.toolTaskId), [13]);
  assert.ok(f.tasks.filter(t => t.conversationId === 2).every(t => !t.abortRequested));
  const key = '2:request-0';
  assert.equal(f.state.requests[key].terminal.status, 'native-conflict'); assert.equal(f.state.active[key], undefined);
  assert.equal(f.events.filter(e => e.type === 'native-identity-conflict').length, 1);
});

test('an invalid second chain rejects the entire mark plan before the first task is changed', async () => {
  for (const change of [
    f => { f.tasks[3].state.checkpoint.arguments = { key: 'foreign', payload: 'payload-1', version: 1 }; },
    f => { f.tasks[3].owner = 5; },
    f => { f.entries[3].byTaskId = 5; },
    f => { f.entries[3].model[0].content[0].arguments = { key: 'foreign' }; },
    f => { f.tasks[2].state.on = [7]; },
    f => { f.tasks[3].state.status = 'running'; },
    f => { f.submissions.push({ ...f.submissions[1], id: 'foreign-submission' }); },
    f => { f.tasks.push({ ...f.tasks[3], id: 'foreign-tool' }); },
  ]) {
    const f = fixture(); change(f);
    await assert.rejects(f.run());
    assert.deepEqual(f.calls.filter(c => c.type === 'abortTask'), []);
    assert.ok(f.tasks.every(t => !t.abortRequested));
  }
});

test('a running Harness is rejected before reads, marks or emitted success', async () => {
  const f = fixture(); f.controls.scheduling = 'running';
  await assert.rejects(f.run(), /paused Harness/);
  assert.equal(f.calls.length, 1); assert.deepEqual(f.events, []);
});

test('unexpected scheduling after a mark fails without claiming a completed preabort', async () => {
  const f = fixture(); f.controls.resumeAfterMark = true;
  await assert.rejects(f.run(), /paused Harness/);
  assert.equal(f.calls.filter(c => c.type === 'abortTask').length, 1); assert.deepEqual(f.events, []);
});

test('a successful abortTask return without a persisted mark is rejected', async () => {
  const f = fixture(); f.controls.mark = false;
  await assert.rejects(f.run(), /abort-marked before resume/);
  assert.deepEqual(f.events, []);
});
