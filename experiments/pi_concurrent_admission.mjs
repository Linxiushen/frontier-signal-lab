// A finite, opt-in caller for two distinct native reservations and one exact retry.
// No queue, retry policy, locking, native mutation or transport is added here.
import assert from 'node:assert/strict';

export function createConcurrentAdmissionRound({ emit = () => {}, timeoutMs = 8000 } = {}) {
  assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 8000);
  let active;
  return {
    async gate(phase, key) {
      if (phase !== 'before-reserve' || !active) return;
      const round = active;
      const remaining = round.remaining.get(key);
      assert.ok(remaining > 0, 'Unregistered concurrent admission');
      round.remaining.set(key, remaining - 1);
      round.arrivals++;
      emit({ type: 'concurrent-reserve-arrival', round: round.id, key, arrival: round.arrivals });
      if (round.arrivals === 3) {
        assert.ok([...round.remaining.values()].every(n => n === 0));
        emit({ type: 'concurrent-reserve-release', round: round.id, arrivals: 3 });
        round.release();
      }
      await round.barrier;
    },
    async run(service, requests, id) {
      assert.equal(active, undefined, 'One finite concurrent round per service');
      assert.ok(Array.isArray(requests) && requests.length === 2);
      const [first, second] = requests;
      assert.ok(first.key !== second.key && first.conversation !== second.conversation);
      assert.ok(typeof id === 'string' && id.length > 0);
      const calls = [first, second, first];
      let release, reject;
      const barrier = new Promise((resolve, fail) => { release = resolve; reject = fail; });
      const round = { id, barrier, release, arrivals: 0,
        remaining: new Map([[first.key, 2], [second.key, 1]]) };
      active = round;
      const timer = setTimeout(() => reject(new Error('Concurrent reserve barrier deadline')), timeoutMs);
      const started = performance.now();
      emit({ type: 'concurrent-admission-open', round: id, keys: calls.map(r => r.key), calls: 3 });
      try {
        const results = await Promise.allSettled(calls.map(r => service.admit(
          r.conversation, r.requestId, r.payload, r.version)));
        for (const result of results) if (result.status === 'rejected') throw result.reason;
        assert.equal(round.arrivals, 3, 'Every caller must reach the real reservation entry');
        const values = results.map(r => r.value);
        assert.deepEqual([values[0].status, values[2].status].sort(), ['admit', 'duplicate']);
        assert.equal(values[1].status, 'admit');
        assert.equal(values[0].submissionId, values[2].submissionId, 'Exact retry must bind the original submission');
        for (let i = 0; i < 3; i++) {
          assert.equal(values[i].key, calls[i].key);
          assert.ok(Number.isSafeInteger(values[i].submissionId) && values[i].submissionId > 0);
        }
        emit({ type: 'concurrent-admission-close', round: id, keys: calls.map(r => r.key),
          results: values, elapsed_ms: performance.now() - started });
        return [values[0].status === 'admit' ? values[0] : values[2], values[1]];
      } finally {
        clearTimeout(timer);
        active = undefined;
      }
    },
  };
}
