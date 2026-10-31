// Optional single-owner queue: await offer/tick serially. Histories are not bounded.
// Admission/authority/idempotency remain in the native service.
export class BoundedRetryQueue {
  constructor({ admit, clock, emit, retry, capacity = 4, maxAttempts = 8,
    intervalMs = 20, deadlineMs = 200 }) {
    if (!Number.isInteger(capacity) || capacity < 1 || !Number.isInteger(maxAttempts) || maxAttempts < 1 ||
        !Number.isFinite(intervalMs) || intervalMs <= 0 || !Number.isFinite(deadlineMs) || deadlineMs <= 0)
      throw new TypeError('Finite positive queue/attempt/time bounds required');
    Object.assign(this, { admit, clock, emit, retry, capacity, maxAttempts, intervalMs, deadlineMs });
    this.pending = []; this.finished = []; this.maximumPending = 0;
  }
  finish(entry, disposition, result) {
    const value = { ...entry, disposition, result, finishedMs: this.clock() };
    this.finished.push(value);
    this.emit({ type: 'queue-finish', id: entry.request.id, disposition, attempts: entry.attempts,
      pending: this.pending.length, result });
    return value;
  }
  async attempt(entry) {
    entry.attempts++;
    const at = this.clock(), result = await this.admit(entry.request);
    entry.lastResult = result;
    this.emit({ type: 'queue-attempt', id: entry.request.id, attempt: entry.attempts, atMs: at, result });
    return result;
  }
  async offer(request) {
    const entry = { request, offeredMs: this.clock(), attempts: 0 };
    const result = await this.attempt(entry);
    if (result.status !== 'overloaded') return this.finish(entry, result.status, result);
    if (!this.retry) return this.finish(entry, 'refused', result);
    if (this.pending.length >= this.capacity) return this.finish(entry, 'backpressured', result);
    entry.nextMs = this.clock() + this.intervalMs;
    this.pending.push(entry); this.maximumPending = Math.max(this.maximumPending, this.pending.length);
    this.emit({ type: 'queue-pending', id: request.id, pending: this.pending.length });
    return undefined;
  }
  async tick() {
    for (const entry of [...this.pending]) {
      if (this.clock() < entry.nextMs) continue;
      if (this.clock() - entry.offeredMs >= this.deadlineMs || entry.attempts >= this.maxAttempts) {
        this.pending.splice(this.pending.indexOf(entry), 1);
        this.finish(entry, 'exhausted', entry.lastResult); continue;
      }
      const result = await this.attempt(entry);
      if (result.status !== 'overloaded') {
        this.pending.splice(this.pending.indexOf(entry), 1);
        this.finish(entry, result.status, result);
      } else entry.nextMs = this.clock() + this.intervalMs;
    }
  }
}
