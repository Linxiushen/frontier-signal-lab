// Optional native ToolTask caller with a separately persisted local HTTP effect.
// Single-owner recovery links the original native request across separate commits.
// No external exactly-once or concurrent-owner guarantee.
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { runtimeUrls, loadBackgroundContext, admissionDecision, payloadFingerprint } from './pi_durable_service_v2.mjs';
import { effectIdentity, validateEffectReceipt } from './pi_effect_http_client.mjs';

export function effectDecision(state, args, conversationId, aborted) {
  const request = state.requests[args.key];
  if (aborted || request?.cancelled) return 'aborted';
  if (request?.terminal?.status === 'native-conflict') return 'conflict';
  if (!request || request.conversation !== conversationId || request.version !== args.version ||
      request.payload !== args.payload || request.fingerprint !== payloadFingerprint(args.payload)) return 'conflict';
  const authority = state.authority[conversationId];
  if (!authority?.allowed || authority.version !== args.version) return 'denied';
  return state.effects[args.key] ? 'existing' : 'commit';
}

export async function openGenerationService({ runtimeDirectory, database, phaseGate, emit, providerApi, admissionGate = async () => {}, cancellationGate = async () => {}, effectClient, effectScope }) {
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
  dispatcher = makeEffectDispatcher({ harness, State, context, client: effectClient, emit, effectScope });
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

// This host owns its reservation, not any native row sharing its request ID.
// A collision permanently retires only this host reservation. It never aborts,
// rewrites, adopts or deletes the colliding native submission or its task chain.
export function quarantineConflict(state, key, native, entry) {
  const request = state.requests[key];
  if (!request || key !== `${request.conversation}:${request.requestId}` || !state.active[key])
    throw new Error('Expected exact active host reservation');
  try { validateSubmissionIdentity(request, native, entry); return undefined; }
  catch (error) {
    if (error.message !== 'Native request identity/content mismatch; refusing reconciliation') throw error;
    const terminal = { status: 'native-conflict', nativeSubmissionId: native.id, nativeType: native.type };
    request.terminal = terminal;
    delete state.active[key];
    return terminal;
  }
}

// Conversation.abort() enables scheduling for the entire Session. Mark every
// exact cancelled/denied recovered chain through public APIs while still paused,
// before the first conversation abort can let another checkpoint run. This is a
// single-owner recovery boundary, not a fence against a concurrent resumer.
export async function preparePausedRecoveryAborts({ harness, State, context, emit = () => {} }) {
  const paused = async () => {
    const inspection = await harness.inspect(context);
    assert.equal(inspection.scheduling, 'paused', 'Recovery requires a paused Harness');
    return inspection;
  };
  const inspection = await paused();
  const records = inspection.tasks.map(t => t.record);
  assert.equal(new Set(records.map(t => t.id)).size, records.length, 'Duplicate inspected task');
  const plans = await harness.commit(async tx => {
    const state = await tx.doc(State), plans = [], conflicts = [];
    // Validate the complete batch before applying any native abort mark.
    for (const key of Object.keys(state.active)) {
      const request = state.requests[key];
      assert.ok(request, 'Missing active recovery request');
      const native = await tx.submissionByRequest(request.conversation, request.requestId);
      if (!native) continue;
      const user = native.entry === undefined ? undefined : await tx.entry(native.entry);
      const conflict = quarantineConflict(state, key, native, user);
      if (conflict) { conflicts.push({ type: 'native-identity-conflict', key, ...conflict }); continue; }
      if (!(request.cancelled || request.effectDenied) || ['done', 'unanswered'].includes(native.status)) continue;
      assert.equal(native.status, 'placed', 'Recovery abort requires an exact placed chain');
      assert.deepEqual(inspection.submissions.filter(s => s.conversationId === request.conversation), [native],
        'Recovery conversation must contain exactly its original placed submission');
      const tasks = records.filter(t => t.conversationId === request.conversation);
      assert.equal(tasks.length, 2, 'Recovery abort refuses additional or missing native work');
      const tool = tasks.find(t => t.kind === 'pi.tool'), generation = tasks.find(t => t.kind === 'pi.generation');
      assert.ok(tool && generation, 'Recovery requires one native generation/tool pair');
      assert.equal(tool.version, 2); assert.equal(generation.version, 1);
      assert.equal(tool.background, false); assert.equal(generation.background, false);
      assert.equal(tool.owner, generation.id); assert.equal(generation.owner, undefined);
      assert.deepEqual(generation.input, {});
      const args = { key, payload: request.payload, version: request.version };
      assert.equal(tool.state.status, 'pending');
      assert.deepEqual(tool.state.checkpoint, { phase: 'execute', arguments: args, replay: 'safe' });
      assert.equal(tool.input.kind, 'model');
      const assistant = await tx.entry(tool.input.assistant);
      assert.ok(assistant && assistant.kind === 'pi.assistant');
      assert.equal(assistant.conversationId, request.conversation); assert.equal(assistant.byTaskId, generation.id);
      assert.equal(assistant.model?.length, 1); assert.equal(assistant.model[0].role, 'assistant');
      const callId = `call-${payloadFingerprint(key).slice(0, 24)}`;
      assert.deepEqual(tool.input, { kind: 'model', assistant: assistant.id, callId });
      assert.deepEqual(assistant.model[0].content.filter(c => c.type === 'toolCall'),
        [{ type: 'toolCall', id: callId, name: 'frontier_effect', arguments: args }]);
      assert.equal(generation.state.status, 'waiting');
      assert.deepEqual(generation.state.on, [tool.id]); assert.equal(generation.state.policy, 'allSettled');
      assert.deepEqual(generation.state.checkpoint,
        { phase: 'tools', assistant: assistant.id, tools: [tool.id], pending: [] });
      for (const task of tasks) assert.deepEqual(await tx.task(task.id), task, 'Inspected native chain changed');
      plans.push({ key, conversation: request.conversation, submissionId: native.id,
        generationTaskId: generation.id, toolTaskId: tool.id });
    }
    assert.equal(new Set(plans.flatMap(p => [p.generationTaskId, p.toolTaskId])).size, plans.length * 2,
      'Recovery chains must not share native tasks');
    return { plans, conflicts };
  }, context);
  await paused();
  for (const plan of plans.plans) for (const id of [plan.generationTaskId, plan.toolTaskId]) {
    await paused();
    assert.equal(await harness.abortTask(id, context), 'marked');
    await paused();
  }
  const final = await paused();
  for (const plan of plans.plans) {
    for (const id of [plan.generationTaskId, plan.toolTaskId])
      assert.equal(final.tasks.find(t => t.record.id === id)?.record.abortRequested, true,
        'Every recovered native task must be abort-marked before resume');
    emit({ type: 'recovery-native-preabort', ...plan, scheduling: final.scheduling });
  }
  for (const conflict of plans.conflicts) emit(conflict);
  return plans.plans;
}

// Recover an unknown transport reply by observing the separate store first.
// Recording an existing effect after cancellation acknowledges history; it does not
// authorize another mutation. Permission checks and network commit are not atomic.
export function makeEffectDispatcher({ harness, State, context, client, emit = () => {}, effectScope = 'default' }) {
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
    await harness.commit(async tx => {
      const current = await tx.doc(State), own = current.effectIntents[key];
      if (!own || Object.keys(expected).some(k => own.identity[k] !== expected[k])) throw new Error('Effect disposition identity changed');
      own.status = status;
      if (status === 'denied') current.requests[key].effectDenied = true;
    }, context);
    emit({ type: 'effect-refused', key, status });
    return status;
  } };
}
