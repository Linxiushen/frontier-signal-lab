// Opt-in scoped-v2 loopback transport. Inject into openGenerationService as effectClient.
import http from 'node:http';
import { effectIdentity, validateEffectReceipt } from './pi_effect_http_client.mjs';
export { effectFingerprint, effectIdentity, validateEffectReceipt } from './pi_effect_http_client.mjs';

export function createEffectClient(base, { scope, timeoutMs = 2000, maxBytes = 16384, emit = () => {} } = {}) {
  if (typeof scope !== 'string' || !/^[a-z0-9-]{1,64}$/.test(scope)) throw new Error('Explicit stable effect scope required');
  const url = new URL(base);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.pathname !== '/' ||
      url.username || url.password || url.search || url.hash || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 ||
      !Number.isSafeInteger(maxBytes) || maxBytes < 1) throw new Error('Requires bounded exact loopback endpoint');
  async function request(method, path, body, signal) {
    if (!/^\/(effects\/[a-z0-9-]{1,64}\/[^/?#]+|authority|hold|snapshot)$/.test(path)) throw new Error('Invalid effect path');
    if (path.startsWith('/effects/') && path.split('/')[2] !== scope) throw new Error('Foreign effect scope');
    if (['/authority', '/hold'].includes(path) && body?.scope !== scope) throw new Error('Foreign effect scope');
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
        headers: { 'x-frontier-fixture': 'local-fixture-v2-scoped', ...(encoded ? { 'content-type': 'application/json', 'content-length': encoded.length } : {}) } }, res => {
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
  const path = identity => {
    if (identity.scope !== scope) throw new Error('Foreign effect scope');
    effectIdentity(identity, identity.conversation, scope);
    return `/effects/${scope}/${encodeURIComponent(identity.key)}`;
  };
  return { scope, request,
    async lookup(identity, signal) {
      const r = await request('GET', path(identity), undefined, signal);
      if (r.status === 404) return undefined;
      if (r.status !== 200) throw new Error(`Effect lookup HTTP${r.status}`);
      return validateEffectReceipt(identity, r.body);
    },
    async apply(identity, signal) {
      const r = await request('POST', path(identity), identity, signal);
      if (r.status === 403) return { denied: true };
      if (r.status !== 200 && r.status !== 201) throw new Error(`Effect apply HTTP${r.status}`);
      return { receipt: validateEffectReceipt(identity, r.body), created: r.status === 201 };
    } };
}

// Native callers keep the existing Harness/GenerationTask/ToolTask owner. Only
// this opt-in transport and its separately named server/database are replaced.
export async function openScopedGenerationService({ effectBase, transportOptions, ...options }) {
  if (options.effectClient) throw new Error('Scoped service constructs its own effect client');
  const client = createEffectClient(effectBase, { ...transportOptions, scope: options.effectScope });
  const { openGenerationService } = await import('./pi_generation_http_service.mjs');
  return openGenerationService({ ...options, effectClient: client });
}
