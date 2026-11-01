// Optional real Harness/GenerationTask/ToolTask adapter with a local faux provider.
// Single-owner recovery links the original native request across separate commits.
// No external exactly-once or concurrent-owner guarantee.
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { runtimeUrls, loadBackgroundContext, admissionDecision, payloadFingerprint } from './pi_durable_service_v2.mjs';

export function effectDecision(state, args, conversationId, aborted) {
  const request = state.requests[args.key];
  if (aborted || request?.cancelled) return 'aborted';
  if (!request || request.conversation !== conversationId || request.version !== args.version ||
      request.payload !== args.payload || request.fingerprint !== payloadFingerprint(args.payload)) return 'conflict';
  const authority = state.authority[conversationId];
  if (!authority?.allowed || authority.version !== args.version) return 'denied';
  return state.effects[args.key] ? 'existing' : 'commit';
}

export async function openGenerationService({ runtimeDirectory, database, phaseGate, emit, providerApi, admissionGate = async () => {} }) {
  const urls = runtimeUrls(runtimeDirectory);
  const { Harness, createRegistry, defineDoc, defineTool } = await import(urls.runtimeUrl);
  const { openNodeSqliteStorage } = await import(urls.sqliteUrl);
  const context = await loadBackgroundContext(urls.contextUrl);
  const aiUrl = pathToFileURL(resolve(runtimeDirectory, 'node_modules/@earendil-works/pi-ai/dist/index.js')).href;
  const { Type, createModels, fauxProvider, fauxAssistantMessage, fauxToolCall } = await import(aiUrl);
  const State = defineDoc({ kind: 'frontier.generation-admission-service', version: 1, scope: 'session',
    initial: () => ({ capacity: 2, authority: {}, requests: {}, active: {}, effects: {} }), checkpointWhen: () => true });
  const effect = defineTool({ name: 'frontier_effect', description: 'Commit one authorized local fixture effect.',
    parameters: Type.Object({ key: Type.String(), payload: Type.String(), version: Type.Integer() }), replay: 'safe',
    execute: async (args, api, ctx) => {
      emit({ type: 'tool-enter', key: args.key, taskId: api.taskId, conversation: api.conversationId, callId: api.callId });
      await phaseGate('before-effect', args.key, ctx.abortSignal);
      let decision;
      await api.commit(async tx => {
        const state = await tx.doc(State);
        decision = effectDecision(state, args, api.conversationId, ctx.abortSignal?.aborted === true);
        if (decision === 'commit') state.effects[args.key] = { count: 1, payload: args.payload };
      }, ctx);
      emit({ type: 'tool-effect', key: args.key, taskId: api.taskId, decision });
      if (decision === 'commit' || decision === 'existing') await phaseGate('after-effect', args.key, ctx.abortSignal);
      return { output: [{ type: 'text', text: decision }], isError: !['commit', 'existing'].includes(decision),
        control: { terminate: true } };
    } });
  const extension = { name: 'frontier-generation', tools: [effect] };
  const registry = createRegistry(); registry.install(extension);
  const faux = fauxProvider({ tokensPerSecond: 0, ...(providerApi === undefined ? {} : { api: providerApi }) });
  emit({ type: 'provider-identity', api: faux.getModel().api, provider: faux.getModel().provider,
    model: faux.getModel().id, mode: providerApi === undefined ? 'default-dynamic' : 'configured-stable' });
  // Finite factory inventory: a runaway extra generation exhausts it and fails acceptance.
  faux.setResponses(Array.from({ length: 16 }, () => (transcript, options) => {
    const user = transcript.messages.filter(m => m.role === 'user').at(-1);
    if (!user || typeof user.content !== 'string') throw new Error('Expected exact JSON user input');
    const args = JSON.parse(user.content);
    emit({ type: 'provider-request', key: args.key, api: faux.getModel().api, providerSession: options?.sessionId,
      offeredTools: transcript.messages.filter(m => m.role === 'system').flatMap(m => m.toolsAdded ?? []).map(t => t.name) });
    return fauxAssistantMessage(fauxToolCall('frontier_effect', args, { id: `call-${payloadFingerprint(args.key).slice(0, 24)}` }),
      { stopReason: 'toolUse' });
  }));
  const models = createModels(); models.setProvider(faux.provider);
  const harness = await Harness.open(await openNodeSqliteStorage(database), { registry, models,
    settings: { retry: { enabled: false }, compaction: { enabled: false } },
    onReport: (error, info) => emit({ type: 'runtime-report', error: String(error), info }) }, context);
  const publications = [];
  harness.subscribeCommits(p => {
    for (const c of p.changes) if (c.type === 'document' && c.record.kind === 'frontier.generation-admission-service') {
      if (publications.length >= 256) throw new Error('Bounded observation inventory exceeded');
      publications.push({ type: 'committed-state', seq: p.seq, state: c.value });
    }
  });
  const conversation = id => harness.conversation(id, context);
  async function reconcileOne(key) {
    const observed = await harness.commit(async tx => {
      const state = await tx.doc(State), request = state.requests[key];
      if (!request) throw new Error('Missing durable reservation');
      if (!state.active[key]) return { terminal: true, id: request.submissionId };
      const existing = await tx.submissionByRequest(request.conversation, request.requestId);
      if (existing) {
        const entry = existing.entry === undefined ? undefined : await tx.entry(existing.entry);
        validateSubmissionIdentity(request, existing, entry);
        return { request: { ...request }, existing };
      }
      const action = reservationAction(state, request);
      if (action !== 'submit') {
        request.terminal = { status: action };
        delete state.active[key];
        return { terminal: true };
      }
      return { request: { ...request } };
    }, context);
    if (observed.terminal) return observed.id;
    const r = observed.request;
    if (observed.existing && r.cancelled && !['done', 'unanswered'].includes(observed.existing.status))
      await (await conversation(r.conversation)).abort(context);
    const submission = observed.existing ?? await (await conversation(r.conversation)).submit({
      type: 'input', requestId: r.requestId, whenBusy: 'reject',
      content: JSON.stringify({ key, payload: r.payload, version: r.version }) }, context);
    // A failed submit leaves a durable pending reservation; errors propagate.
    // Stable native request IDs make an unknown reply safe to reconcile later.
    await admissionGate('after-submit', key);
    await harness.commit(async tx => {
      const state = await tx.doc(State), current = state.requests[key];
      if (!current || current.fingerprint !== r.fingerprint || current.version !== r.version ||
          current.requestId !== r.requestId || current.conversation !== r.conversation)
        throw new Error('Reservation identity changed');
      const native = await tx.submissionByRequest(r.conversation, r.requestId);
      if (!native || native.id !== submission.id) throw new Error('Native request link changed');
      validateSubmissionIdentity(current, native, native.entry === undefined ? undefined : await tx.entry(native.entry));
      current.submissionId = submission.id;
    }, context);
    await admissionGate('after-link', key);
    return submission.id;
  }
  return { harness, context,
    snapshot: () => harness.snapshot(State, context),
    flush() { for (const p of publications.splice(0)) emit(p); },
    async createConversation() {
      return (await harness.createConversation({ ownership: { kind: 'ownerless' }, agent: {
        model: { provider: faux.getModel().provider, modelId: faux.getModel().id },
        thinkingLevel: 'off', extensions: [extension] } }, context)).id;
    },
    async authorize(id, version, allowed) {
      await harness.commit(async tx => { (await tx.doc(State)).authority[id] = { version, allowed }; }, context);
    },
    async admit(id, requestId, payload, version) {
      const fingerprint = payloadFingerprint(payload), started = performance.now();
      const key = `${id}:${requestId}`;
      await admissionGate('before-reserve', key);
      const decision = await harness.commit(async tx => {
        const state = await tx.doc(State), d = admissionDecision(state, id, requestId, fingerprint, version);
        if (d.status === 'admit') {
          state.requests[d.key] = { fingerprint, conversation: id, requestId, payload, version };
          state.active[d.key] = true;
        } else if (d.status === 'duplicate' && state.requests[d.key].version !== version) {
          return { status: 'conflict', key: d.key };
        }
        return d;
      }, context);
      if (decision.status === 'admit' || decision.status === 'duplicate') {
        await admissionGate('after-reserve', key);
        const linked = await reconcileOne(key);
        if (linked) decision.submissionId = linked;
      }
      emit({ type: 'admission', conversation: id, requestId, payload, version, ...decision, elapsed_ms: performance.now() - started });
      return decision;
    },
    async reconcile() {
      const state = await harness.snapshot(State, context);
      for (const key of Object.keys(state.active)) await reconcileOne(key);
    },
    async cancelRequest(id, requestId) {
      const key = `${id}:${requestId}`;
      const existing = await harness.commit(async tx => {
        const state = await tx.doc(State), request = state.requests[key];
        if (!request) throw new Error('Unknown durable request');
        request.cancelled = true;
        return await tx.submissionByRequest(id, requestId);
      }, context);
      if (existing && !['done', 'unanswered'].includes(existing.status)) await (await conversation(id)).abort(context);
      await reconcileOne(key);
    },
    async reap() {
      const state = await harness.snapshot(State, context), terminal = [];
      for (const key of Object.keys(state.active)) {
        const id = state.requests[key].submissionId;
        if (!id) continue; // reconcile() owns pending reservations and their capacity.
        const submission = await (await harness.submission(id, context)).status(context);
        if (submission.status === 'done' || submission.status === 'unanswered') terminal.push({ key, submission });
      }
      if (terminal.length) await harness.commit(async tx => {
        const current = await tx.doc(State);
        for (const r of terminal) { delete current.active[r.key]; current.requests[r.key].terminal = r.submission; }
      }, context);
      return terminal;
    },
    async cancel(id) { return (await conversation(id)).abort(context); },
    async replay(id, requestId, key, payload, version) {
      return (await conversation(id)).submit({ type: 'input', requestId, whenBusy: 'reject',
        content: JSON.stringify({ key, payload, version }) }, context);
    },
    async close() { await harness.close(context); },
  };
}

export function validateSubmissionIdentity(request, native, entry) {
  const expected = JSON.stringify({ key: `${request.conversation}:${request.requestId}`, payload: request.payload, version: request.version });
  if (native.type !== 'input' || native.conversationId !== request.conversation || native.requestId !== request.requestId ||
      !entry || entry.kind !== 'pi.user' || entry.conversationId !== request.conversation ||
      entry.model?.length !== 1 || entry.model[0].role !== 'user' || entry.model[0].content !== expected)
    throw new Error('Native request identity/content mismatch; refusing reconciliation');
}

export function reservationAction(state, request) {
  if (request.cancelled) return 'cancelled-before-submit';
  const authority = state.authority[request.conversation];
  return authority?.allowed && authority.version === request.version ? 'submit' : 'denied-before-submit';
}
