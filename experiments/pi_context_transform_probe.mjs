/** Execute complete pinned pi context transforms, with the authentic parent as a negative control. */
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const vendor = resolve(root, 'third_party/pi-context');
const hash = (value) => createHash('sha256').update(value).digest('hex');
const clone = (value) => structuredClone(value);

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.freeze(value);
    for (const item of Object.values(value)) freeze(item);
  }
  return value;
}

const modelA = { id: 'fixture-model-a', provider: 'fixture-provider-a', api: 'fixture-api-a', input: ['text', 'image'] };
const user = (text, timestamp) => ({ role: 'user', content: text, timestamp });
const assistant = (content, timestamp, overrides = {}) => ({ role: 'assistant', provider: modelA.provider,
  api: modelA.api, model: modelA.id, content, stopReason: 'stop', timestamp, ...overrides });
const text = (value) => ({ type: 'text', text: value });
const thinking = (value) => ({ type: 'thinking', thinking: value });
const toolResult = (id, name, content, timestamp) => ({ role: 'toolResult', toolCallId: id, toolName: name,
  content: [text(content)], isError: false, timestamp });

function fixtures() {
  const sameContent = [thinking('SAME_READABLE'),
    { type: 'thinking', thinking: '', thinkingSignature: 'opaque-fixture-signed-empty' },
    { type: 'thinking', thinking: '', redacted: true },
    { type: 'text', text: 'visible answer', textSignature: 'opaque-fixture-text' }];
  const same = [user('question', 1), assistant(sameContent, 2)];
  const cases = [{ scenario: 'same_identity_opaque_reasoning', model: modelA, input: same,
    expected_merged: clone(same), expected_parent: clone(same), foreign_markers: [] }];

  const call = { type: 'toolCall', id: 'call|foreign:1', name: 'lookup',
    arguments: { query: 'visible query', options: { limit: 2 } }, thoughtSignature: 'opaque-foreign-tool' };
  const foreignModel = { ...modelA, id: 'fixture-model-b' };
  const foreignInput = [user('look up the item', 10), assistant([thinking('FOREIGN_MODEL_REASONING'),
    { type: 'thinking', thinking: '', thinkingSignature: 'opaque-foreign-signed' },
    { type: 'thinking', thinking: '', redacted: true },
    { type: 'text', text: 'performing lookup', textSignature: 'opaque-foreign-text' }, call], 11,
  { stopReason: 'toolUse' }), toolResult(call.id, call.name, 'lookup result', 12), user('continue', 13)];
  const plainCall = { type: 'toolCall', id: call.id, name: call.name, arguments: clone(call.arguments) };
  const foreignMerged = [clone(foreignInput[0]), assistant([text('performing lookup'), plainCall], 11,
    { stopReason: 'toolUse' }), clone(foreignInput[2]), clone(foreignInput[3])];
  const foreignParent = clone(foreignMerged);
  foreignParent[1].content.unshift(text('FOREIGN_MODEL_REASONING'));
  cases.push({ scenario: 'model_identity_change_tools', model: foreignModel, input: foreignInput,
    expected_merged: foreignMerged, expected_parent: foreignParent, foreign_markers: ['FOREIGN_MODEL_REASONING'] });

  for (const [field, value, name, marker] of [
    ['provider', 'fixture-provider-b', 'provider_identity_change', 'FOREIGN_PROVIDER_REASONING'],
    ['api', 'fixture-api-b', 'api_identity_change', 'FOREIGN_API_REASONING'],
  ]) {
    const input = [user('handoff', 20), assistant([thinking(marker), text('public answer')], 21)];
    cases.push({ scenario: name, model: { ...modelA, [field]: value }, input,
      expected_merged: [clone(input[0]), assistant([text('public answer')], 21)],
      expected_parent: [clone(input[0]), assistant([text(marker), text('public answer')], 21)],
      foreign_markers: [marker] });
  }

  const alternate = [user('first', 30), assistant([thinking('SAME_A_FIRST'), text('A first')], 31),
    user('second', 32), assistant([thinking('FOREIGN_B_MIDDLE'), text('B middle')], 33, { model: foreignModel.id }),
    user('third', 34), assistant([
      { type: 'thinking', thinking: '', thinkingSignature: 'opaque-A-return' }, text('A final')], 35)];
  const alternatingMerged = clone(alternate);
  alternatingMerged[3].content = [text('B middle')];
  const alternatingParent = clone(alternatingMerged);
  alternatingParent[3].content.unshift(text('FOREIGN_B_MIDDLE'));
  cases.push({ scenario: 'alternating_models_a_b_a', model: modelA, input: alternate,
    expected_merged: alternatingMerged, expected_parent: alternatingParent, foreign_markers: ['FOREIGN_B_MIDDLE'] });

  const incomplete = [user('retryable request', 40),
    assistant([thinking('PARTIAL_ERROR'), { type: 'toolCall', id: 'never-error', name: 'never', arguments: {} }], 41,
      { stopReason: 'error', errorMessage: 'fixture error' }),
    user('retry after error', 42),
    assistant([thinking('PARTIAL_ABORT'), { type: 'toolCall', id: 'never-abort', name: 'never', arguments: {} }], 43,
      { stopReason: 'aborted' }),
    user('retry after abort', 44), assistant([text('completed answer')], 45)];
  const completeOnly = [clone(incomplete[0]), clone(incomplete[2]), clone(incomplete[4]), clone(incomplete[5])];
  cases.push({ scenario: 'error_and_aborted_turns', model: modelA, input: incomplete,
    expected_merged: clone(completeOnly), expected_parent: clone(completeOnly), foreign_markers: [] });

  const call1 = { type: 'toolCall', id: 'literal|call:1', name: 'first', arguments: { value: 1 },
    thoughtSignature: 'opaque-same-tool' };
  const call2 = { type: 'toolCall', id: 'literal|call:2', name: 'second', arguments: { value: 2 } };
  const toolFlow = [user('two tools', 50), assistant([thinking('SAME_TOOL_REASONING'), call1, call2], 51,
    { stopReason: 'toolUse' }), { role: 'system', content: 'interposed system instruction' },
  toolResult(call2.id, call2.name, 'second result', 52), toolResult(call1.id, call1.name, 'first result', 53),
  user('finish', 54)];
  const reordered = [clone(toolFlow[0]), clone(toolFlow[1]), clone(toolFlow[3]), clone(toolFlow[4]),
    clone(toolFlow[2]), clone(toolFlow[5])];
  cases.push({ scenario: 'complete_tools_with_system_message', model: modelA, input: toolFlow,
    expected_merged: clone(reordered), expected_parent: clone(reordered), foreign_markers: [] });

  const blank = [user('blank thinking', 60), assistant([thinking(''), thinking('  \t  '), text('ordinary answer')], 61)];
  const blankExpected = [clone(blank[0]), assistant([text('ordinary answer')], 61)];
  cases.push({ scenario: 'unsigned_blank_thinking', model: modelA, input: blank,
    expected_merged: clone(blankExpected), expected_parent: clone(blankExpected), foreign_markers: [] });
  return cases;
}

async function loadSources() {
  const rawProvenance = await readFile(resolve(vendor, 'provenance.json'));
  const provenance = JSON.parse(rawProvenance.toString('utf8'));
  if (provenance.license !== 'MIT') throw new Error('Expected reviewed MIT license');
  const licenseHash = hash(await readFile(resolve(vendor, 'LICENSE')));
  if (licenseHash !== provenance.license_sha256) throw new Error('Pinned license SHA256 mismatch');
  const sources = {};
  for (const version of ['parent', 'merged']) {
    const spec = provenance.sources[version];
    const sourcePath = resolve(vendor, spec.file);
    const sourceHash = hash(await readFile(sourcePath));
    if (sourceHash !== spec.source_sha256) throw new Error(`Pinned ${version} source SHA256 mismatch`);
    // The only upstream import is import type; Node erases it. No loader hooks or source rewriting.
    const module = await import(pathToFileURL(sourcePath).href);
    if (typeof module.transformMessages !== 'function') throw new Error(`Missing ${version} transformMessages export`);
    sources[version] = { module, path: sourcePath, sha256: sourceHash, spec };
  }
  return { sources, provenance, provenance_sha256: hash(rawProvenance), license_sha256: licenseHash };
}

function visibleForeign(output, markers) {
  return output.flatMap((message) => message.role === 'assistant' ? message.content : [])
    .filter((block) => block.type === 'text' && markers.includes(block.text)).map((block) => block.text);
}

async function runProbe() {
  const loaded = await loadSources();
  const cases = fixtures();
  const runs = [];
  for (const fixture of cases) {
    const observations = {};
    for (const version of ['parent', 'merged']) {
      const input = freeze(clone(fixture.input));
      const model = freeze(clone(fixture.model));
      const before = hash(canonical({ input, model }));
      const output = loaded.sources[version].module.transformMessages(input, model);
      const after = hash(canonical({ input, model }));
      const expected = fixture[`expected_${version}`];
      const exposed = visibleForeign(output, fixture.foreign_markers);
      observations[version] = { output, output_sha256: hash(canonical(output)), expected_output: expected,
        exact_output_matches: canonical(output) === canonical(expected),
        input_and_model_sha256_before: before, input_and_model_sha256_after: after,
        input_and_model_unchanged: before === after, visible_foreign_reasoning: exposed,
        desired_foreign_reasoning_boundary: exposed.length === 0 };
    }
    const expectedNegative = fixture.foreign_markers.length > 0;
    const controlObserved = canonical(observations.parent.visible_foreign_reasoning)
      === canonical(fixture.foreign_markers);
    const passed = ['parent', 'merged'].every((version) => observations[version].exact_output_matches
      && observations[version].input_and_model_unchanged)
      && observations.merged.desired_foreign_reasoning_boundary && controlObserved;
    runs.push({ scenario: fixture.scenario, model: fixture.model, input: fixture.input,
      input_sha256: hash(canonical(fixture.input)), foreign_reasoning_markers: fixture.foreign_markers,
      parent_expected_negative_control: expectedNegative, parent_control_matches_expectation: controlObserved,
      ...observations, passed });
  }
  const unchanged = {};
  for (const [version, source] of Object.entries(loaded.sources)) {
    unchanged[version] = hash(await readFile(source.path)) === source.sha256;
  }
  const report = { schema_version: 1, experiment: 'complete pinned pi context transformation primitive',
    config: { randomness: 'none', fixed_fixture_timestamps: true,
      fixture_sha256: hash(canonical(cases)), probe_sha256: hash(await readFile(fileURLToPath(import.meta.url))),
      provenance_sha256: loaded.provenance_sha256, license: 'MIT', license_sha256: loaded.license_sha256,
      sources: Object.fromEntries(Object.entries(loaded.sources).map(([version, source]) => [version,
        { path: `third_party/pi-context/${source.spec.file}`, commit: source.spec.commit,
          source_sha256: source.sha256, source_url: source.spec.raw_url }])),
      execution: 'Direct full-file native TypeScript imports; transformMessages(input, model); no third argument',
      runtime_dependency_substitution: false, module_hooks: false },
    scope: 'Only transformMessages context transformation. No provider requests, full harness, signature validation or model behavior measured.',
    limitations: [
      'Opaque signatures and redaction flags are synthetic sentinels; retaining them does not establish cryptographic or provider validity.',
      'The authentic parent intentionally fails the desired no-foreign-thinking-as-visible-text boundary on four traces; that expected negative result is preserved.',
      'Every successful tool-call fixture has matching results. Orphan synthesis, its Date.now timestamp and optional ID normalizer are not exercised.',
      'The complete modules also export splitErrorToolResultImages; that separate helper and image downgrade/null normalization branches are not exercised.',
      'Eight bounded fixtures do not establish transport acceptance, actual model handoff, persistence, liveness, quality, token cost or production reliability.',
      'The upstream fix predates this pass and is not a new merge or our algorithmic invention.',
    ], source_files_unchanged: unchanged, runs,
    summary: { traces: runs.length, module_executions: runs.length * 2,
      parent_negative_control_traces: runs.filter((row) => row.parent_expected_negative_control).length,
      parent_desired_boundary_failures: runs.filter((row) => !row.parent.desired_foreign_reasoning_boundary).length,
      merged_desired_boundary_failures: runs.filter((row) => !row.merged.desired_foreign_reasoning_boundary).length },
    all_passed: runs.every((row) => row.passed) && Object.values(unchanged).every(Boolean) };
  report.result_sha256 = hash(canonical(report));
  return report;
}

function markdown(report) {
  const lines = ['# pi context transformation probe', '',
    'Runs both complete, unchanged upstream TypeScript files directly. No runtime imports, module hooks, substitutions or normalization callback are used.', '',
    '| Trace | Parent exact oracle | Merged exact oracle | Parent desired boundary | Merged desired boundary | Inputs unchanged |',
    '|---|---|---|---|---|---|'];
  for (const row of report.runs) lines.push(`| ${row.scenario} | ${row.parent.exact_output_matches} | ${row.merged.exact_output_matches} | ${row.parent.desired_foreign_reasoning_boundary} | ${row.merged.desired_foreign_reasoning_boundary} | ${row.parent.input_and_model_unchanged && row.merged.input_and_model_unchanged} |`);
  lines.push('', 'The authentic parent is an expected negative control: readable reasoning from another model becomes visible text in four traces. The merged version drops it. Same-identity signed/redacted empty blocks, ordinary text and complete tool-call/results match their exact oracles.', '',
    `Traces: ${report.summary.traces}; module executions: ${report.summary.module_executions}; merged boundary failures: ${report.summary.merged_desired_boundary_failures}.`, '',
    `Result SHA256 (canonical JSON excluding result_sha256): \`${report.result_sha256}\`.`, '',
    '## Scope', '', report.scope, '', ...report.limitations.map((item) => `- ${item}`), '');
  return lines.join('\n');
}

async function main() {
  let output = resolve(root, 'results/pi-context-transform');
  for (let i = 2; i < process.argv.length; i++) {
    if (process.argv[i] !== '--output') throw new Error(`Unknown argument: ${process.argv[i]}`);
    if (!process.argv[i + 1] || process.argv[i + 1].startsWith('--')) throw new Error('--output requires a directory');
    output = resolve(process.argv[++i]);
  }
  const report = await runProbe();
  await mkdir(output, { recursive: true });
  await writeFile(resolve(output, 'probe.json'), JSON.stringify(report, null, 2) + '\n', 'utf8');
  await writeFile(resolve(output, 'report.md'), markdown(report), 'utf8');
  process.stdout.write(JSON.stringify({ ...report.summary, all_passed: report.all_passed,
    result_sha256: report.result_sha256 }) + '\n');
  if (!report.all_passed) process.exitCode = 1;
}

main().catch((error) => { process.stderr.write(`${error.name}: ${error.message}\n`); process.exitCode = 1; });
