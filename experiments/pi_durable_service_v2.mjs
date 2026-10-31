// Optional Node adapter. The caller supplies an installed, integrity-pinned Pi runtime.
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export function runtimeUrls(directory) {
  const entry = (name, path) => pathToFileURL(resolve(directory, 'node_modules', '@earendil-works', name, 'dist', path)).href;
  return { runtimeUrl: entry('pi-durable', 'index.js'),
    contextUrl: entry('chord', 'context/index.js'),
    sqliteUrl: entry('pi-durable', 'storage/sqlite/node.js') };
}

export async function loadBackgroundContext(contextUrl) {
  const { BACKGROUND_CONTEXT: context } = await import(contextUrl);
  if (!context || typeof context.value !== 'function' || !context.telemetry)
    throw new TypeError('Expected BACKGROUND_CONTEXT from @earendil-works/chord/context');
  return context;
}

export function admissionDecision(state, session, requestId, fingerprint, version) {
  const key = `${session}:${requestId}`;
  const authority = state.authority[session];
  if (!authority?.allowed || authority.version !== version) return { status: 'unauthorized', key };
  const previous = state.requests[key];
  if (previous) return previous.fingerprint === fingerprint
    ? { status: 'duplicate', taskId: previous.taskId, key }
    : { status: 'conflict', key };
  if (Object.keys(state.active).length >= state.capacity) return { status: 'overloaded', key };
  return { status: 'admit', key };
}

export function payloadFingerprint(payload) {
  // This interface accepts a string payload, so serialization has one unambiguous representation.
  if (typeof payload !== 'string') throw new TypeError('String payload required');
  return createHash('sha256').update(payload).digest('hex');
}

export async function openService({ runtimeUrl, contextUrl, sqliteUrl, database, capacity = 2, phaseGate, emit }) {
  const { Harness, createRegistry, defineDoc, defineTask } = await import(runtimeUrl);
  const context = await loadBackgroundContext(contextUrl);
  const { openNodeSqliteStorage } = await import(sqliteUrl);
  const State = defineDoc({ kind: 'frontier.service', version: 1, scope: 'session',
    initial: () => ({ capacity, authority: {}, requests: {}, active: {}, effects: {}, denied: [], cancelled: [] }),
    checkpointWhen: () => true });
  const Work = defineTask({ name: 'frontier.effect', version: 1,
    initial: () => ({ phase: 'effect' }),
    phases: {
      effect: async (task, runtime, ctx) => {
        emit({ type: 'phase', phase: 'effect', key: task.input.key, taskId: task.id });
        await phaseGate('effect', task.input.key, runtime.signal);
        await runtime.commit(async (tx) => {
          const state = await tx.doc(State);
          const auth = state.authority[task.input.session];
          // Resolve current authority inside the SAME transaction that commits the durable effect.
          if (!auth?.allowed || auth.version !== task.input.version) {
            state.denied.push(task.input.key);
            delete state.active[task.input.key];
            return { status: 'terminal', outcome: { status: 'completed', result: 'denied' } };
          }
          if (!state.effects[task.input.key]) state.effects[task.input.key] = { count: 1, payload: task.input.payload };
          return { status: 'running', checkpoint: { phase: 'finish' } };
        }, ctx);
      },
      finish: async (task, runtime, ctx) => {
        emit({ type: 'phase', phase: 'finish', key: task.input.key, taskId: task.id });
        if (task.input.hold) await phaseGate('finish', task.input.key, runtime.signal);
        await runtime.commit(async (tx) => {
          delete (await tx.doc(State)).active[task.input.key];
          return { status: 'terminal', outcome: { status: 'completed', result: 'committed' } };
        }, ctx);
      },
    },
    abort: async (task, runtime, ctx) => {
      await runtime.commit(async (tx) => {
        const state = await tx.doc(State);
        state.cancelled.push(task.input.key);
        delete state.active[task.input.key];
        return { status: 'terminal', outcome: { status: 'aborted' } };
      }, ctx);
    },
  });
  const registry = createRegistry();
  registry.install({ name: 'frontier-service', tasks: [Work] });
  const harness = await Harness.open(await openNodeSqliteStorage(database), {
    registry,
    models: () => { emit({ type: 'provider-access-denied' }); throw new Error('This service slice permits no model/provider access'); },
    onReport: (error, info) => emit({ type: 'runtime-report', error: String(error), info }),
  }, context);
  // Retain adopted immutable values; the synchronous observer does no IO or Session calls.
  const publications = [];
  harness.subscribeCommits(publication => {
    for (const change of publication.changes) {
      if (change.type === 'document' && change.record.kind === 'frontier.service') {
        if (publications.length >= 256) throw new Error('Commit observation budget exceeded');
        publications.push({ type: 'committed-state', seq: publication.seq, state: change.value });
      }
    }
  });
  const snapshot = () => harness.snapshot(State, context);
  return {
    harness, context, snapshot,
    flushCommitEvents() { for (const publication of publications.splice(0)) emit(publication); },
    async createSession() { return (await harness.createConversation({ ownership: { kind: 'ownerless' } }, context)).id; },
    async authorize(session, version, allowed) {
      await harness.commit(async (tx) => { (await tx.doc(State)).authority[session] = { version, allowed }; }, context);
    },
    async admit(session, requestId, payload, version, hold = false) {
      const fingerprint = payloadFingerprint(payload);
      const started = performance.now();
      const result = await harness.commit(async (tx) => {
        const state = await tx.doc(State);
        const decision = admissionDecision(state, session, requestId, fingerprint, version);
        if (decision.status !== 'admit') return decision;
        const input = { key: decision.key, session, payload, version, hold };
        const taskId = await tx.createTask(Work, input, { conversationId: session, ownership: { kind: 'conversation' } });
        state.requests[decision.key] = { fingerprint, taskId };
        state.active[decision.key] = taskId;
        return { ...decision, taskId };
      }, context);
      emit({ type: 'admission', session, requestId, version, ...result, elapsed_ms: performance.now() - started });
      return result;
    },
    async cancel(taskId) { return harness.abortTask(taskId, context); },
    async settle(taskId) { return harness.waitForTask(taskId, context); },
    async close() { await harness.close(context); },
  };
}
