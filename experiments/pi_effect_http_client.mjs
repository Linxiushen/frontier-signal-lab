// Bounded, opt-in loopback transport for a separate durable effect service.
import http from 'node:http';
import { createHash } from 'node:crypto';

export const effectFingerprint = value => createHash('sha256').update(value).digest('hex');
export function effectIdentity(args, conversation, scope = 'default') {
  if (typeof args.key !== 'string' || typeof args.payload !== 'string' || !Number.isSafeInteger(args.version) ||
      !(typeof conversation === 'string' || Number.isSafeInteger(conversation) && conversation > 0) ||
      typeof scope !== 'string' || !/^[a-z0-9-]{1,64}$/.test(scope) || !args.key.startsWith(`${conversation}:`)) throw new Error('Invalid effect identity');
  return { key: args.key, payload: args.payload, version: args.version, conversation, scope,
    fingerprint: effectFingerprint(args.payload) };
}
export function validateEffectReceipt(expected, actual) {
  if (!actual || actual.count !== 1 || Object.keys(expected).some(k => actual[k] !== expected[k]))
    throw new Error('Foreign effect receipt; refusing acknowledgement');
  return actual;
}
export function createEffectClient(base, { timeoutMs = 2000, maxBytes = 16384, emit = () => {} } = {}) {
  const url = new URL(base);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.pathname !== '/' ||
      url.username || url.password || url.search || url.hash || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 ||
      !Number.isSafeInteger(maxBytes) || maxBytes < 1) throw new Error('Requires bounded exact loopback endpoint');
  async function request(method, path, body, signal) {
    if (!/^\/(effects\/[^/?#]+|authority|hold|snapshot)$/.test(path)) throw new Error('Invalid effect path');
    const encoded = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    if (encoded?.length > 4096) throw new Error('Effect request byte ceiling');
    const started = performance.now();
    return new Promise((resolve, reject) => {
      let done = false, observedResponseBytes = 0;
      const finish = (error, value) => {
        if (done) return; done = true; clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        emit({ type: 'http-result', method, path, elapsed_ms: performance.now() - started,
          request_body_bytes: encoded?.length ?? 0, response_body_bytes: observedResponseBytes,
          ...(error ? { error: String(error) } : { status: value.status, bytes: value.bytes }) });
        error ? reject(error) : resolve(value);
      };
      const req = http.request({ hostname: '127.0.0.1', port: url.port, path, method, agent: false,
        headers: { 'x-frontier-fixture': 'local-fixture-v1', ...(encoded ? { 'content-type': 'application/json', 'content-length': encoded.length } : {}) } }, res => {
        const chunks = []; let bytes = 0;
        res.on('data', data => {
          bytes += data.length;
          observedResponseBytes = bytes;
          if (bytes > maxBytes) { const error = new Error('Effect response byte ceiling'); finish(error); req.destroy(error); }
          else chunks.push(data);
        });
        res.on('error', error => finish(error));
        res.on('end', () => {
          try { finish(undefined, { status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString('utf8')), bytes }); }
          catch (error) { finish(error); }
        });
      });
      const abort = () => req.destroy(signal.reason instanceof Error ? signal.reason : new Error('Effect request aborted'));
      // Monotonic wall timer covers connect, headers and body; inactivity timeouts alone do not.
      const timer = setTimeout(() => req.destroy(new Error('Effect request wall deadline')), timeoutMs);
      req.on('error', error => finish(error));
      if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, { once: true });
      req.end(encoded);
    });
  }
  const path = key => `/effects/${encodeURIComponent(key)}`;
  return { request,
    async lookup(identity, signal) {
      const r = await request('GET', path(identity.key), undefined, signal);
      if (r.status === 404) return undefined;
      if (r.status !== 200) throw new Error(`Effect lookup HTTP${r.status}`);
      return validateEffectReceipt(identity, r.body);
    },
    async apply(identity, signal) {
      const r = await request('POST', path(identity.key), identity, signal);
      if (r.status === 403) return { denied: true };
      if (r.status !== 200 && r.status !== 201) throw new Error(`Effect apply HTTP${r.status}`);
      return { receipt: validateEffectReceipt(identity, r.body), created: r.status === 201 };
    } };
}
