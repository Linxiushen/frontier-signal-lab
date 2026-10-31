import assert from 'node:assert/strict';
import test from 'node:test';
import { BoundedRetryQueue } from '../experiments/pi_bounded_retry.mjs';

function fixture(options = {}) {
  let now = 0, status = 'overloaded'; const calls = [], events = [];
  const queue = new BoundedRetryQueue({ retry: true, clock: () => now, emit: e => events.push(e),
    admit: async request => { calls.push(request.id); return { status }; }, ...options });
  return { queue, calls, events, time: value => { now = value; }, status: value => { status = value; } };
}
test('pending admission is bounded and declines overflow without retaining it', async () => {
  const f = fixture({ capacity: 2 });
  for (const id of ['a', 'b', 'c']) await f.queue.offer({ id });
  assert.equal(f.queue.pending.length, 2); assert.equal(f.queue.maximumPending, 2);
  assert.equal(f.queue.finished[0].disposition, 'backpressured');
  f.status('admit'); f.time(20); await f.queue.tick();
  assert.equal(f.queue.pending.length, 0); assert.equal(f.calls.length, 5);
  assert.deepEqual(f.queue.finished.map(e => e.disposition), ['backpressured', 'admit', 'admit']);
});
test('refusal baseline makes exactly one call with no hidden queue', async () => {
  const f = fixture({ retry: false }); await f.queue.offer({ id: 'a' });
  f.time(100); await f.queue.tick();
  assert.equal(f.calls.length, 1); assert.equal(f.queue.pending.length, 0);
  assert.equal(f.queue.finished[0].disposition, 'refused');
});
test('attempt ceiling and deadline terminate overload rather than looping', async () => {
  for (const options of [{ maxAttempts: 2 }, { deadlineMs: 21 }]) {
    const f = fixture(options); await f.queue.offer({ id: 'a' });
    f.time(19); await f.queue.tick(); assert.equal(f.calls.length, 1);
    f.time(20); await f.queue.tick(); assert.equal(f.calls.length, 2);
    f.time(40); await f.queue.tick(); assert.equal(f.calls.length, 2);
    assert.equal(f.queue.finished[0].disposition, 'exhausted'); assert.equal(f.queue.pending.length, 0);
  }
});
test('retry uses fresh native authority and terminal non-overload responses', async () => {
  for (const status of ['unauthorized', 'conflict', 'duplicate']) {
    const f = fixture(); await f.queue.offer({ id: 'a' }); f.time(20); f.status(status); await f.queue.tick();
    assert.equal(f.calls.length, 2); assert.equal(f.queue.finished[0].disposition, status);
    assert.equal(f.queue.pending.length, 0);
  }
});
test('exhaustion retains the last native overload identity', async () => {
  for (const options of [{ maxAttempts: 1 }, { deadlineMs: 10 }]) {
    const result = { status: 'overloaded', key: 'conversation:request' };
    const f = fixture({ ...options, admit: async () => result });
    await f.queue.offer({ id: 'a' }); f.time(20); await f.queue.tick();
    assert.equal(f.queue.finished[0].disposition, 'exhausted');
    assert.equal(f.queue.finished[0].result, result);
    assert.equal(f.events.find(e => e.type === 'queue-finish').result, result);
    assert.equal(f.queue.pending.length, 0);
  }
});
test('invalid resource bounds fail before admission', () => {
  for (const options of [{ capacity: 0 }, { maxAttempts: 0 }, { intervalMs: 0 }, { deadlineMs: Infinity }])
    assert.throws(() => fixture(options), TypeError);
});
