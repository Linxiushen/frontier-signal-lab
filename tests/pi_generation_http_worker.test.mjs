// Pure gate controls only: importing the worker never opens the optional runtime.
import assert from 'node:assert/strict';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { createTransportGate } from '../scripts/pi_generation_http_worker.mjs';

test('actual worker gates only the transport gap, independently for each service', async () => {
  const events = [], released = new Set();
  const gate = createTransportGate({ service: 1, released, emit: e => events.push(e) });
  await gate('before-effect', 'c:r'); await gate('after-effect', 'c:r');
  assert.deepEqual(events, []);
  let settled = false;
  const pending = gate('before-transport', 'c:r').then(() => { settled = true; });
  await delay(5); assert.equal(settled, false);
  released.add('0:c:r'); await delay(5); assert.equal(settled, false);
  released.add('1:c:r'); await pending;
  assert.deepEqual(events.map(e => e.type), ['transport-held', 'transport-released']);
});

test('actual held transport observes cancellation without reaching release', async () => {
  const events = [], controller = new AbortController();
  const gate = createTransportGate({ service: 0, released: new Set(), emit: e => events.push(e) });
  const pending = gate('before-transport', 'c:r', controller.signal);
  controller.abort(new Error('cancelled control'));
  await assert.rejects(pending, error => /cancelled control/.test(String(error.cause ?? error)));
  assert.deepEqual(events.map(e => e.type), ['transport-held']);
  await assert.rejects(gate('before-effect', 'c:r', controller.signal), /cancelled control/);
});

test('unknown phase is refused rather than silently opening a new gap', async () => {
  const gate = createTransportGate({ service: 0, released: new Set(), emit: () => {} });
  await assert.rejects(gate('unregistered-gap', 'c:r'), /Unknown effect phase/);
});
