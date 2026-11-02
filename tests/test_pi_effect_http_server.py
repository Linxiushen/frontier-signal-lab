import hashlib
from pathlib import Path
import tempfile
import unittest

from experiments.pi_effect_http_server import EffectStore, identity


def item(key='c:r', payload='value', version=1, conversation='c', scope='default'):
    return dict(key=key, payload=payload, version=version, conversation=conversation,
                scope=scope, fingerprint=hashlib.sha256(payload.encode()).hexdigest())


class EffectStoreTests(unittest.TestCase):
    def test_native_session_local_numeric_ids_keep_independent_current_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EffectStore(Path(directory) / 'effects.sqlite')
            store.authorize(2, 1, False, scope='service0')
            store.authorize(2, 1, True, scope='service1')
            denied = item(key='2:db0', conversation=2, scope='service0')
            allowed = item(key='2:db1', conversation=2, scope='service1')
            self.assertEqual(store.effect('POST', denied['key'], denied)[0], 403)
            self.assertEqual(store.effect('POST', allowed['key'], allowed)[0], 201)
            self.assertEqual(store.snapshot()['authority'], [['service0', 2, 1, 0], ['service1', 2, 1, 1]])
            self.assertEqual(store.snapshot()['effects'], [{**allowed, 'count': 1}])

    def test_separate_store_reopen_and_repeated_reply_do_not_repeat_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'effects.sqlite'
            first = EffectStore(path)
            first.authorize('c', 1, True)
            status, receipt = first.effect('POST', 'c:r', item())
            self.assertEqual(status, 201)
            reopened = EffectStore(path)
            self.assertEqual(reopened.effect('GET', 'c:r'), (200, receipt))
            self.assertEqual(reopened.effect('POST', 'c:r', item()), (200, receipt))
            self.assertEqual(reopened.snapshot()['effects'], [receipt])

    def test_current_authority_and_conflicting_content_have_no_new_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EffectStore(Path(directory) / 'effects.sqlite')
            store.authorize('c', 1, True)
            self.assertEqual(store.effect('POST', 'c:r', item())[0], 201)
            store.authorize('c', 2, False)
            self.assertEqual(store.effect('POST', 'c:r', item(payload='foreign'))[0], 409)
            self.assertEqual(store.effect('POST', 'c:new', item(key='c:new'))[0], 403)
            self.assertEqual(store.effect('POST', 'c:r', item())[0], 200)
            self.assertEqual(len(store.snapshot()['effects']), 1)

    def test_malformed_and_boolean_version_refused_before_transaction(self):
        for changed in [{'version': True}, {'fingerprint': 'wrong'}, {'key': 'foreign:r'}, {'extra': 'field'}]:
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                identity({**item(), **changed})

    def test_sql_delimiters_remain_opaque_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EffectStore(Path(directory) / 'effects.sqlite')
            store.authorize('c', 1, True)
            value = item(key="c:';DROP TABLE effects;--", payload='\u96ea\n\u0000')
            self.assertEqual(store.effect('POST', value['key'], value)[0], 201)
            self.assertEqual(store.snapshot()['effects'], [{**value, 'count': 1}])


if __name__ == '__main__':
    unittest.main()
