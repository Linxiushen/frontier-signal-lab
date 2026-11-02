import hashlib
from pathlib import Path
import tempfile
import unittest

from experiments.pi_effect_http_server import EffectStore
from experiments.pi_scoped_effect_http_server import ScopedEffectStore


def item(scope='service0', key='1:same-request', payload='first', version=1):
    return dict(key=key, payload=payload, version=version, conversation=1,
                scope=scope, fingerprint=hashlib.sha256(payload.encode()).hexdigest())


class ScopedEffectStoreTests(unittest.TestCase):
    def test_same_canonical_key_has_independent_receipts_in_two_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScopedEffectStore(Path(directory) / 'effects-scoped.sqlite')
            first = item()
            second = item(scope='service1', payload='different payload')
            for value in (first, second):
                store.authorize(1, 1, True, scope=value['scope'])
            self.assertEqual(store.effect('POST', first['scope'], first['key'], first),
                             (201, {**first, 'count': 1}))
            self.assertEqual(store.effect('GET', second['scope'], second['key']),
                             (404, {'error': 'missing'}))
            self.assertEqual(store.effect('POST', second['scope'], second['key'], second),
                             (201, {**second, 'count': 1}))
            for value in (first, second):
                self.assertEqual(store.effect('GET', value['scope'], value['key']),
                                 (200, {**value, 'count': 1}))
            self.assertEqual(store.snapshot()['effects'],
                             [{**first, 'count': 1}, {**second, 'count': 1}])

    def test_same_scope_replay_and_conflict_preserve_the_original_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScopedEffectStore(Path(directory) / 'effects-scoped.sqlite')
            value = item()
            store.authorize(1, 1, True, scope=value['scope'])
            self.assertEqual(store.effect('POST', value['scope'], value['key'], value)[0], 201)
            self.assertEqual(store.effect('POST', value['scope'], value['key'], value),
                             (200, {**value, 'count': 1}))
            conflicting = item(payload='changed')
            self.assertEqual(store.effect('POST', value['scope'], value['key'], conflicting),
                             (409, {'error': 'identity-conflict'}))
            snapshot = store.snapshot()
            self.assertEqual(snapshot['effects'], [{**value, 'count': 1}])
            self.assertEqual([row[1:] for row in snapshot['attempts']],
                             [['POST', value['scope'], value['key'], status]
                              for status in (201, 200, 409)])

    def test_path_scope_or_key_mismatch_is_rejected_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScopedEffectStore(Path(directory) / 'effects-scoped.sqlite')
            value = item()
            store.authorize(1, 1, True, scope='service0')
            store.authorize(1, 1, True, scope='service1')
            before = store.snapshot()
            for path_scope, path_key in [('service1', value['key']),
                                         (value['scope'], '1:other'),
                                         ('service1', '1:other')]:
                with self.subTest(scope=path_scope, key=path_key):
                    with self.assertRaises(AssertionError):
                        store.effect('POST', path_scope, path_key, value)
                    self.assertEqual(store.snapshot(), before)

    def test_new_writes_require_current_authority_in_the_requested_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScopedEffectStore(Path(directory) / 'effects-scoped.sqlite')
            # Identical numeric conversation IDs in another scope grant nothing here.
            store.authorize(1, 1, True, scope='service1')
            for authority in ('absent', 'wrong-version', 'revoked'):
                with self.subTest(authority=authority):
                    if authority == 'wrong-version':
                        store.authorize(1, 2, True, scope='service0')
                    elif authority == 'revoked':
                        store.authorize(1, 1, False, scope='service0')
                    value = item(key='1:' + authority)
                    self.assertEqual(store.effect('POST', value['scope'], value['key'], value),
                                     (403, {'error': 'current-authority-denied'}))
                    self.assertEqual(store.snapshot()['effects'], [])
            self.assertEqual([row[2] for row in store.snapshot()['attempts']],
                             ['service0', 'service0', 'service0'])

    def test_revocation_preserves_old_receipt_but_does_not_allow_a_new_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScopedEffectStore(Path(directory) / 'effects-scoped.sqlite')
            value = item()
            store.authorize(1, 1, True, scope=value['scope'])
            status, receipt = store.effect('POST', value['scope'], value['key'], value)
            self.assertEqual(status, 201)
            store.authorize(1, 2, False, scope=value['scope'])
            self.assertEqual(store.effect('GET', value['scope'], value['key']), (200, receipt))
            self.assertEqual(store.effect('POST', value['scope'], value['key'], value), (200, receipt))
            conflicting = item(payload='changed')
            self.assertEqual(store.effect('POST', value['scope'], value['key'], conflicting)[0], 409)
            new = item(key='1:new', version=2)
            self.assertEqual(store.effect('POST', new['scope'], new['key'], new)[0], 403)
            self.assertEqual(store.snapshot()['effects'], [receipt])

    def test_reopened_sqlite_keeps_both_scope_counts_at_one(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'effects-scoped.sqlite'
            first = ScopedEffectStore(path)
            values = [item(), item(scope='service1', payload='second')]
            for value in values:
                first.authorize(1, 1, True, scope=value['scope'])
                self.assertEqual(first.effect('POST', value['scope'], value['key'], value)[0], 201)
            reopened = ScopedEffectStore(path)
            for value in values:
                expected = {**value, 'count': 1}
                self.assertEqual(reopened.effect('GET', value['scope'], value['key']), (200, expected))
                self.assertEqual(reopened.effect('POST', value['scope'], value['key'], value), (200, expected))
            self.assertEqual(reopened.snapshot()['effects'], [{**value, 'count': 1} for value in values])
            with reopened.connect() as database:
                self.assertEqual(database.execute('PRAGMA user_version').fetchone(), (2,))

    def test_legacy_key_only_database_is_rejected_without_changing_its_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'effects.sqlite'
            legacy = EffectStore(path)
            value = item()
            legacy.authorize(1, 1, True, scope=value['scope'])
            self.assertEqual(legacy.effect('POST', value['key'], value)[0], 201)
            before_snapshot = legacy.snapshot()
            before_files = {file.name: file.read_bytes() for file in Path(directory).iterdir()}
            with self.assertRaisesRegex(ValueError, 'legacy migration is not supported'):
                ScopedEffectStore(path)
            self.assertEqual({file.name: file.read_bytes() for file in Path(directory).iterdir()}, before_files)
            self.assertEqual(legacy.snapshot(), before_snapshot)


if __name__ == '__main__':
    unittest.main()
