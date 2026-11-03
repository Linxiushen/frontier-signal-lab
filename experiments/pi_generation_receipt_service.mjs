// Opt-in receipt-monotonic variant of the existing native generation adapter.
// The pinned original service remains available for rollback and frozen audits.
// Same-owner overlapping callbacks only; no concurrent-owner/remote atomicity claim.
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { runtimeUrls, loadBackgroundContext, admissionDecision, payloadFingerprint } from './pi_durable_service_v2.mjs';
import { effectIdentity, validateEffectReceipt } from './pi_effect_http_client.mjs';
import { effectDecision, validateSubmissionIdentity, reservationAction, quarantineConflict, preparePausedRecoveryAborts } from './pi_generation_http_service.mjs';

export async function openReceiptGenerationService({ runtimeDirectory, database, phaseGate, emit, providerApi, admissionGate = async () => {}, cancellationGate = async () => {}, effectClient, effectScope }) {
  if (!effectClient) throw new Error('Explicit optional HTTP effect client required');
  if (typeof effectScope !== 'string' || !/^[a-z0-9-]{1,64}$/.test(effectScope)) throw new Error('Explicit stable effect scope required');
  const urls = runtimeUrls(runtimeDirectory);
  const { Harness, createRegistry, defineDoc, defineTool } = await import(urls.runtimeUrl);
  const { openNodeSqliteStorage } = await import(urls.sqliteUrl);
  const context = await loadBackgroundContext(urls.contextUrl);
  const aiUrl = pathToFileURL(resolve(runtimeDirectory, 'node_modules/@earendil-works/pi-ai/dist/index.js')).href;
  const { Type, createModels, fauxProvider, fauxAssistantMessage, fauxToolCall } = await import(aiUrl);
  const State = defineDoc({ kind: 'frontier.generation-admission-service', version: 1, scope: 'session',
    initial: () => ({ capacity: 2, authority: {}, requests: {}, active: {}, effects: {}, effectIntents: {} }), checkpointWhen: () => true });
  const effect = defineTool({ name: 'frontier_effect', description: 'Commit one authorized local fixture effect.',
    parameters: Type.Object({ key: Type.String(), payload: Type.String(), version: Type.Integer() }), replay: 'safe',
    execute: async (args, api, ctx) => {
      emit({ type: 'tool-enter', key: args.key, taskId: api.taskId, conversation: api.conversationId, callId: api.callId });
      await phaseGate('before-effect', args.key, ctx.abortSignal);
      let decision;
      await api.commit(async tx => {
        const state = await tx.doc(State);
        decision = effectDecision(state, args, api.conversationId, ctx.abortSignal?.aborted === true);
        if (decision === 'commit' || decision === 'existing') {
          const expected = effectIdentity(args, api.conversationId, effectScope);
          const old = state.effectIntents[args.key];
          if (old && Object.keys(expected).some(k => old.identity[k] !== expected[k])) throw new Error('Effect intent identity changed');
          if (!old) state.effectIntents[args.key] = { identity: expected, status: 'pending' };
        }
      }, ctx);
      if (decision === 'commit' || decision === 'existing') {
        await phaseGate('before-transport', args.key, ctx.abortSignal);
        decision = await dispatcher.dispatch(args.key, ctx.abortSignal);
      }
      emit({ type: 'tool-effect', key: args.key, taskId: api.taskId, decision });
      if (decision === 'commit' || decision === 'existing') await phaseGate('after-effect', args.key, ctx.abortSignal);
      return { output: [{ type: 'text', text: decision }], isError: !['commit', 'existing'].includes(decision),
        control: { terminate: true } };
    } });
  let dispatcher;
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
  dispatcher = makeReceiptDispatcher({ harness, State, context, client: effectClient, emit, effectScope });
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
        const conflict = quarantineConflict(state, key, existing, entry);
        if (conflict) return { terminal: true, conflict };
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
    if (observed.conflict) emit({ type: 'native-identity-conflict', key, ...observed.conflict });
    if (observed.terminal) return observed.id;
    const r = observed.request;
    if (observed.existing && (r.cancelled || r.effectDenied) && !['done', 'unanswered'].includes(observed.existing.status))
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
      assert.equal((await harness.inspect(context)).scheduling, 'paused', 'Recovery requires a paused Harness');
      const state = await harness.snapshot(State, context);
      for (const [key, intent] of Object.entries(state.effectIntents))
        if (intent.status === 'pending') await dispatcher.dispatch(key);
      await preparePausedRecoveryAborts({ harness, State, context, emit });
      for (const key of Object.keys(state.active)) await reconcileOne(key);
    },
    async cancelRequest(id, requestId) {
      const key = `${id}:${requestId}`;
      await harness.commit(async tx => {
        const state = await tx.doc(State), request = state.requests[key];
        if (!request) throw new Error('Unknown durable request');
        request.cancelled = true;

      }, context);
      // Durable intent precedes native abort; a restart must reconcile this exact gap.
      await cancellationGate('after-cancel-mark', key);
      // Reconciliation validates the exact native identity before deciding to abort.
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

export function makeReceiptDispatcher({ harness, State, context, client, emit = () => {}, effectScope = 'default' }) {
  function validateHost(state, key, expected) {
    const request = state.requests[key];
    if (!request || key !== expected.key || expected.scope !== effectScope || request.conversation !== expected.conversation ||
        request.payload !== expected.payload || request.version !== expected.version || request.fingerprint !== expected.fingerprint)
      throw new Error('Effect intent no longer matches host identity');
  }
  async function acknowledge(key, expected, receipt, source = 'lookup') {
    validateEffectReceipt(expected, receipt);
    await harness.commit(async tx => {
      const state = await tx.doc(State), intent = state.effectIntents[key];
      validateHost(state, key, expected);
      if (!intent || Object.keys(expected).some(k => intent.identity[k] !== expected[k])) throw new Error('Effect intent changed before acknowledgement');
      state.effects[key] = { count: 1, payload: expected.payload, receipt };
      intent.status = 'committed'; intent.receipt = receipt;
    }, context);
    emit({ type: 'effect-acknowledged', key, receipt, source });
    return 'existing';
  }
  return { async dispatch(key, signal) {
    let state = await harness.snapshot(State, context), intent = state.effectIntents[key];
    if (!intent) throw new Error('Missing durable effect intent');
    if (intent.status !== 'pending') return intent.status === 'committed' ? 'existing' : intent.status;
    const expected = intent.identity;
    validateHost(state, key, expected);
    // This read has no external mutation, and may recover a previous committed
    // effect even when current authority has since been withdrawn.
    const existing = await client.lookup(expected, signal);
    if (existing) return acknowledge(key, expected, existing);
    state = await harness.snapshot(State, context);
    const decision = effectDecision(state, expected, expected.conversation, signal?.aborted === true);
    let status;
    if (decision !== 'commit' && decision !== 'existing') status = decision;
    else {
      const result = await client.apply(expected, signal);
      if (result.receipt) {
        await acknowledge(key, expected, result.receipt, result.created ? 'created' : 'reused');
        return result.created ? 'commit' : 'existing';
      }
      if (!result.denied) throw new Error('Unknown effect response');
      status = 'denied';
    }
    const disposition = await harness.commit(async tx => {
      const current = await tx.doc(State), own = current.effectIntents[key];
      validateHost(current, key, expected);
      if (!own || Object.keys(expected).some(k => own.identity[k] !== expected[k])) throw new Error('Effect disposition identity changed');
      // Another callback may have acknowledged the same effect while this
      // lookup or refusal was in flight. Cancellation cannot undo that receipt.
      if (own.status === 'committed') {
        validateEffectReceipt(expected, own.receipt);
        validateEffectReceipt(expected, current.effects[key]?.receipt);
        return 'existing';
      }
      own.status = status;
      if (status === 'denied') current.requests[key].effectDenied = true;
      return status;
    }, context);
    emit(disposition === 'existing'
      ? { type: 'effect-disposition-superseded', key, status, by: 'committed' }
      : { type: 'effect-refused', key, status: disposition });
    return disposition;
  } };
}
