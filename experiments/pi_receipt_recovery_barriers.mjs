// Controlled scheduling around real transport calls; never manufactures receipts.
import assert from 'node:assert/strict';

export function createRecoveryClient({ client, key, mode, hold, emit = () => {} }) {
  assert.ok(['late-missing', 'late-refusal'].includes(mode));
  let lookups = 0, applies = 0;
  return {
    async lookup(identity, signal) {
      const observed = await client.lookup(identity, signal);
      if (identity.key !== key) return observed;
      const call = ++lookups;
      assert.ok(call <= 2, 'Exactly two overlapping missing reads');
      assert.equal(observed, undefined, 'Barrier requires an actual missing transport response');
      emit({ type: 'race-lookup-missing', key, mode, call });
      if (mode === 'late-missing' && call === 2) await hold('late-missing');
      return observed;
    },
    async apply(identity, signal) {
      if (identity.key !== key) return client.apply(identity, signal);
      const call = ++applies;
      assert.ok(call <= (mode === 'late-missing' ? 1 : 2), 'Bounded effect attempts');
      emit({ type: 'race-apply-ready', key, mode, call });
      if (call === 1) await hold('first-apply');
      const observed = await client.apply(identity, signal);
      emit({ type: 'race-apply-result', key, mode, call, result: observed });
      if (mode === 'late-refusal' && call === 2) {
        assert.deepEqual(observed, { denied: true }, 'Hold only a genuine transport refusal');
        await hold('late-refusal');
      }
      return observed;
    },
  };
}
