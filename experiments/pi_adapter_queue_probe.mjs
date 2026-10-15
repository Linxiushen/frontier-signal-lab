/** Execute the pinned pi adapter primitive over a local node:sqlite stand-in. */
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { registerHooks } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = resolve(root, 'third_party/pi/cloudflare.ts');
const sourceURL = pathToFileURL(sourcePath).href;
const sentinelURL = 'pi-queue-probe:unused-storage';
const sentinelKey = Symbol.for('frontier-signal-lab.pi-storage-sentinel');
globalThis[sentinelKey] = { attempts: 0 };
const hashBytes = (value) => createHash('sha256').update(value).digest('hex');

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

class DeadlineError extends Error {
  constructor(label) { super(`Deadline exceeded: ${label}`); this.name = 'DeadlineError'; }
}

export async function deadline(promise, milliseconds, label) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new DeadlineError(label)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}

function deferred() {
  let release;
  const promise = new Promise((resolvePromise) => { release = resolvePromise; });
  return { promise, release };
}

async function loadPinnedAdapter() {
  const [source, license, rawProvenance] = await Promise.all([
    readFile(sourcePath), readFile(resolve(root, 'third_party/pi/LICENSE')),
    readFile(resolve(root, 'third_party/pi/provenance.json'), 'utf8'),
  ]);
  const provenance = JSON.parse(rawProvenance);
  if (hashBytes(source) !== provenance.source_sha256) throw new Error('Pinned source SHA256 mismatch');
  if (hashBytes(license) !== provenance.license_sha256) throw new Error('Pinned license SHA256 mismatch');
  if (provenance.license !== 'MIT') throw new Error('Expected reviewed MIT source');
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (context.parentURL === sourceURL) {
        if (specifier === './storage.ts') return { url: sentinelURL, shortCircuit: true };
        throw new Error(`Unexpected runtime import from pinned adapter: ${specifier}`);
      }
      return nextResolve(specifier, context);
    },
    load(url, context, nextLoad) {
      if (url === sentinelURL) {
        return { format: 'module', shortCircuit: true,
          source: `export class SqliteStorage { static get open() {
            globalThis[Symbol.for('frontier-signal-lab.pi-storage-sentinel')].attempts++;
            throw new Error('Unused SqliteStorage factory is blocked by the probe sentinel');
          } }` };
      }
      return nextLoad(url, context);
    },
  });
  const module = await import(sourceURL);
  if (typeof module.DurableObjectSqliteDatabase !== 'function') throw new Error('Missing upstream adapter export');
  return { module, provenance, sourceHash: hashBytes(source), licenseHash: hashBytes(license) };
}

function localStorage(events) {
  const database = new DatabaseSync(':memory:');
  database.exec('CREATE TABLE progress (id TEXT PRIMARY KEY, value INTEGER NOT NULL)');
  let active = false;
  const storage = {
    sql: {
      exec(query, ...bindings) {
        const statement = database.prepare(query);
        let rows = [];
        if (statement.columns().length) rows = statement.all(...bindings);
        else statement.run(...bindings);
        let index = 0;
        return { next: () => index < rows.length ? { done: false, value: rows[index++] } : { done: true },
          toArray: () => rows.slice() };
      },
    },
    async transaction(closure) {
      if (active) throw new Error('Nested stand-in transactions are not supported');
      active = true;
      database.exec('BEGIN');
      events.push('storage.begin');
      try {
        const result = await closure();
        database.exec('COMMIT');
        events.push('storage.commit');
        return result;
      } catch (error) {
        database.exec('ROLLBACK');
        events.push('storage.rollback');
        throw error;
      } finally { active = false; }
    },
  };
  return { storage, database, rows: () => storage.sql.exec('SELECT id,value FROM progress ORDER BY id').toArray() };
}

function observe(promise, events, label) {
  return promise.then(
    () => { events.push(`${label}.fulfilled`); return { status: 'fulfilled' }; },
    (error) => { events.push(`${label}.rejected`); return { status: 'rejected', error: error.message }; },
  );
}

async function queuedCase(environment, abort) {
  const { first, second, events, rows } = environment;
  const entered = deferred();
  const release = deferred();
  const transaction = observe(first.transaction(async (handle) => {
    await handle.run('INSERT INTO progress VALUES (?,?)', 'inside', 1);
    events.push('callback.entered');
    entered.release();
    await release.promise;
    events.push('callback.released');
    if (abort) throw new Error('intentional transaction abort');
  }), events, 'transaction');
  await entered.promise;
  let settled = false;
  events.push('queued.submitted');
  const queued = observe(second.run('INSERT INTO progress VALUES (?,?)', 'queued', 2), events, 'queued')
    .then((outcome) => { settled = true; return outcome; });
  await Promise.resolve();
  await Promise.resolve();
  const settledBeforeRelease = settled;
  const rowsBeforeRelease = rows();
  events.push('release.requested');
  release.release();
  const [transactionOutcome, queuedOutcome] = await Promise.all([transaction, queued]);
  return { expected_rows: abort ? [{ id: 'queued', value: 2 }]
    : [{ id: 'inside', value: 1 }, { id: 'queued', value: 2 }],
  transaction_outcome: transactionOutcome, queued_outcome: queuedOutcome,
  queued_settled_before_release: settledBeforeRelease, rows_before_release: rowsBeforeRelease,
  checks: { queued_waited: !settledBeforeRelease,
    queued_row_absent_before_release: !rowsBeforeRelease.some((row) => row.id === 'queued'),
    queued_completed: queuedOutcome.status === 'fulfilled',
    transaction_settlement: transactionOutcome.status === (abort ? 'rejected' : 'fulfilled') } };
}

async function bypassCase(environment) {
  const { first, storage, events, rows } = environment;
  const entered = deferred();
  const release = deferred();
  const transaction = observe(first.transaction(async (handle) => {
    await handle.run('INSERT INTO progress VALUES (?,?)', 'inside', 1);
    entered.release();
    await release.promise;
    throw new Error('intentional transaction abort');
  }), events, 'transaction');
  await entered.promise;
  storage.sql.exec('INSERT INTO progress VALUES (?,?)', 'direct', 3);
  events.push('direct.write.returned');
  const rowsBeforeRelease = rows();
  release.release();
  const outcome = await transaction;
  const finalRows = rows();
  return { expected_rows: [], transaction_outcome: outcome, rows_before_release: rowsBeforeRelease,
    direct_write_completed_before_abort: true,
    completed_direct_write_missing_after_abort: !finalRows.some((row) => row.id === 'direct'),
    control_role: 'Negative control: direct underlying-storage writes bypass the adapter queue.',
    checks: { transaction_rejected: outcome.status === 'rejected',
      direct_write_was_visible: rowsBeforeRelease.some((row) => row.id === 'direct'),
      direct_write_rolled_back: !finalRows.some((row) => row.id === 'direct') } };
}

async function afterAbortCase(environment) {
  const { first, second, events } = environment;
  const aborted = await observe(first.transaction(async (handle) => {
    await handle.run('INSERT INTO progress VALUES (?,?)', 'discarded', 1);
    throw new Error('intentional transaction abort');
  }), events, 'first_transaction');
  const resumed = await observe(second.transaction(async (handle) => {
    await handle.run('INSERT INTO progress VALUES (?,?)', 'after_abort', 4);
  }), events, 'next_transaction');
  return { expected_rows: [{ id: 'after_abort', value: 4 }], first_outcome: aborted, next_outcome: resumed,
    checks: { first_rejected: aborted.status === 'rejected', next_completed: resumed.status === 'fulfilled' } };
}

async function retainedCase(environment, abort) {
  const { first, events } = environment;
  let retained;
  const transaction = await observe(first.transaction(async (handle) => {
    retained = handle;
    await handle.run('INSERT INTO progress VALUES (?,?)', 'kept', 5);
    if (abort) throw new Error('intentional transaction abort');
  }), events, 'transaction');
  const late = await observe(retained.run('INSERT INTO progress VALUES (?,?)', 'late', 99), events, 'retained');
  return { expected_rows: abort ? [] : [{ id: 'kept', value: 5 }],
    transaction_outcome: transaction, retained_handle_outcome: late,
    checks: { transaction_settlement: transaction.status === (abort ? 'rejected' : 'fulfilled'),
      retained_handle_rejected: late.status === 'rejected'
        && late.error === 'SQLite transaction handle is no longer active' } };
}

const scenarios = [
  ['queued_write_commit', (environment) => queuedCase(environment, false)],
  ['queued_write_abort', (environment) => queuedCase(environment, true)],
  ['direct_write_abort_control', bypassCase],
  ['transaction_after_abort', afterAbortCase],
  ['retained_handle_after_commit', (environment) => retainedCase(environment, false)],
  ['retained_handle_after_abort', (environment) => retainedCase(environment, true)],
];

async function runProbe(loaded) {
  const runs = [];
  for (const [name, execute] of scenarios) {
    const events = [];
    const local = localStorage(events);
    try {
      const Adapter = loaded.module.DurableObjectSqliteDatabase;
      const first = new Adapter(local.storage);
      const second = new Adapter(local.storage);
      const result = await deadline(execute({ ...local, first, second, events }), 2000, name);
      const actualRows = local.rows();
      const rowsMatch = canonical(actualRows) === canonical(result.expected_rows);
      runs.push({ scenario: name, ...result, actual_rows: actualRows, rows_match_oracle: rowsMatch,
        passed: rowsMatch && Object.values(result.checks).every(Boolean), deadline_ms: 2000, events });
    } finally { local.database.close(); }
  }
  const versionDB = new DatabaseSync(':memory:');
  const sqliteVersion = versionDB.prepare('SELECT sqlite_version() AS version').get().version;
  versionDB.close();
  const attempts = globalThis[sentinelKey].attempts;
  const report = { schema_version: 1, experiment: 'pinned pi SQLite adapter queue primitive',
    config: { randomness: 'none', node_version: process.version, sqlite_version: sqliteVersion,
      storage: 'node:sqlite DatabaseSync :memory: stand-in', scenario_deadline_ms: 2000,
      overall_deadline_ms: 20000, source_path: 'third_party/pi/cloudflare.ts',
      source_sha256: loaded.sourceHash, source_commit: loaded.provenance.commit,
      source_url: loaded.provenance.source_url, license: 'MIT', license_sha256: loaded.licenseHash },
    dependency_substitution: { specifier: './storage.ts', scope: 'Only imports from the exact pinned adapter URL',
      implementation: 'fail-closed SqliteStorage.open getter sentinel via node:module registerHooks',
      factory_open_attempts: attempts, unused_factory_confirmed: attempts === 0 },
    all_passed: runs.every((row) => row.passed) && attempts === 0,
    limitations: [
      'Executes the unmodified pinned DurableObjectSqliteDatabase class, with the unused higher-level storage factory dependency substituted. This is not the full pi/Pico storage contract.',
      'Local synchronous SQLite SQL and BEGIN/COMMIT/ROLLBACK approximate the structural storage interface; Cloudflare runtime scheduling, isolation and durability are not reproduced.',
      'No power loss, process crash, namespace migration, network service, real external effect or production exactly-once guarantee is tested.',
      'Adapter instances share a queue only when given the same storage object. Direct storage calls bypass it; the negative control demonstrates a completed direct write rolling back with the enclosing transaction.',
      'Promise settlement and exact final SQL rows measure bounded local progress. Six deterministic traces do not establish general liveness or production reliability.',
      'The upstream test suite already contains related queue and direct-write cases; this independent integration probe does not claim to invent them.',
      'No network API is called by the probe or reviewed adapter. This is a source/import restriction, not an operating-system network sandbox.',
    ], runs };
  report.result_sha256 = hashBytes(canonical(report));
  return report;
}

function markdown(report) {
  const lines = ['# Pinned pi adapter queue probe', '',
    'Runs the actual unmodified adapter primitive over a local node:sqlite stand-in. The unused factory import is replaced by an explicit fail-closed sentinel.', '',
    '| Scenario | Promise/guard checks | Exact SQL rows | Passed |', '|---|---|---|---|'];
  for (const row of report.runs) lines.push(`| ${row.scenario} | ${Object.values(row.checks).every(Boolean)} | ${row.rows_match_oracle} | ${row.passed} |`);
  lines.push('', 'The direct-write negative control deliberately bypasses the adapter queue: its returned write is rolled back by the enclosing aborted transaction. It is evidence of the boundary, not a claimed adapter failure.', '',
    `Unused SqliteStorage factory open attempts: **${report.dependency_substitution.factory_open_attempts}**.`, '',
    `Pinned source SHA256: \`${report.config.source_sha256}\`.`, '',
    `Result SHA256 (canonical JSON excluding result_sha256): \`${report.result_sha256}\`.`, '',
    '## Scope', '', ...report.limitations.map((text) => `- ${text}`), '',
    `Upstream source: ${report.config.source_url}`, '');
  return lines.join('\n');
}

function parseArguments(argv) {
  let output = resolve(root, 'results/pi-adapter-queue');
  let mode = 'probe';
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    if (argument === '--output') {
      if (!argv[index + 1] || argv[index + 1].startsWith('--')) throw new Error('--output requires a directory');
      output = resolve(argv[++index]);
    } else if (argument === '--self-test-timeout') mode = 'timeout';
    else if (argument === '--self-test-sentinel') mode = 'sentinel';
    else throw new Error(`Unknown argument: ${argument}`);
  }
  return { output, mode };
}

async function main() {
  const { output, mode } = parseArguments(process.argv.slice(2));
  if (mode === 'timeout') {
    try { await deadline(new Promise(() => {}), 20, 'self-test intentionally unresolved promise'); }
    catch (error) {
      if (!(error instanceof DeadlineError)) throw error;
      process.stdout.write(JSON.stringify({ timeout_detected: true, error: error.name }) + '\n');
      return;
    }
    throw new Error('Deadline self-test failed');
  }
  const loaded = await loadPinnedAdapter();
  if (mode === 'sentinel') {
    try { await loaded.module.openDurableObjectSqliteStorage({}); }
    catch (error) {
      if (globalThis[sentinelKey].attempts !== 1 || !error.message.includes('blocked by the probe sentinel')) throw error;
      process.stdout.write(JSON.stringify({ sentinel_rejected: true, attempts: globalThis[sentinelKey].attempts }) + '\n');
      return;
    }
    throw new Error('Sentinel self-test failed');
  }
  const report = await deadline(runProbe(loaded), 20000, 'overall adapter probe');
  await mkdir(output, { recursive: true });
  await writeFile(resolve(output, 'probe.json'), JSON.stringify(report, null, 2) + '\n', 'utf8');
  await writeFile(resolve(output, 'report.md'), markdown(report), 'utf8');
  process.stdout.write(JSON.stringify({ traces: report.runs.length, all_passed: report.all_passed,
    result_sha256: report.result_sha256 }) + '\n');
  if (!report.all_passed) process.exitCode = 1;
}

main().catch((error) => { process.stderr.write(`${error.name}: ${error.message}\n`); process.exitCode = 1; });
