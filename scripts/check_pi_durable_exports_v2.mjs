// Verify the installed API boundary only. Never open storage or run tasks.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadBackgroundContext, runtimeUrls } from '../experiments/pi_durable_service_v2.mjs';

const [directory] = process.argv.slice(2);
assert.ok(directory, 'Pass the installed runtime directory');
const urls = runtimeUrls(directory);
const context = await loadBackgroundContext(urls.contextUrl);
assert.equal(context.abortSignal, undefined);
assert.equal(typeof context.value, 'function');
assert.equal(typeof context.telemetry.startSpan, 'function');
const packagePath = new URL('../../package.json', urls.contextUrl);
const manifest = JSON.parse(readFileSync(fileURLToPath(packagePath), 'utf8'));
assert.equal(manifest.version, '1.4.0');
assert.equal(manifest.exports['./context'].import, './dist/context/index.js');
const rootUrl = new URL('../index.js', urls.contextUrl).href;
assert.equal((await import(rootUrl)).BACKGROUND_CONTEXT, undefined);
await assert.rejects(loadBackgroundContext(rootUrl), /Expected BACKGROUND_CONTEXT/);
const runtime = await import(urls.runtimeUrl);
for (const name of ['createRegistry', 'defineDoc', 'defineTask'])
  assert.equal(typeof runtime[name], 'function', name);
assert.equal(typeof runtime.Harness.open, 'function');
assert.equal(typeof (await import(urls.sqliteUrl)).openNodeSqliteStorage, 'function');
console.log(JSON.stringify({ status: 'passed', node: process.version, urls,
  validated: ['real-context-export', 'wrong-root-refused', 'real-native-api-exports'],
  storage_opens: 0, harness_opens: 0, tasks: 0, models: 0 }));
