"""Synthetic SQL/schema and malformed-evidence controls; no native/HTTP run."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from experiments.pi_scoped_generation_audit import (
    digest, expected_receipt, read_scoped_endpoint, typed, validate_attempts,
    validate_controls, validate_inventory, verify_copied_endpoint,
)


def inventory():
    ids = {'conversations': [[2, 8], [2, 8]], 'requests': [], 'retries': [], 'conflicts': []}
    for service in range(2):
        for stage in range(3):
            for c, intent in ((0, ('revoke', 'post', 'final')[stage]), (1, ('cancel', 'live', 'final')[stage]), (0, 'overload')):
                conversation = ids['conversations'][service][c]
                request_id = f's{stage}-{intent}'
                r = {'stage': stage, 'service': service, 'scope': f'service{service}',
                     'conversation': conversation, 'requestId': request_id, 'intent': intent,
                     'version': stage + 1, 'key': f'{conversation}:{request_id}',
                     'payload': f'service{service}/{request_id}',
                     'status': 'overloaded' if intent == 'overload' else 'admit'}
                if intent != 'overload':
                    r['submissionId'] = stage * 10 + c + 3
                ids['requests'].append(r)
    finals = [r for r in ids['requests'] if r['stage'] == 2 and r['status'] == 'admit']
    for r in finals:
        ids['retries'].append({'service': r['service'], 'key': r['key'], 'status': 'duplicate', 'submissionId': r['submissionId']})
        ids['conflicts'].append({'service': r['service'], 'key': r['key'], 'status': 'conflict'})
    return ids


def effect_database(db):
    db.executescript('''CREATE TABLE authority(scope TEXT,conversation INTEGER,version INTEGER,allowed INTEGER,PRIMARY KEY(scope,conversation));
        CREATE TABLE effects(scope TEXT,key TEXT,identity TEXT,count INTEGER,PRIMARY KEY(scope,key));
        CREATE TABLE attempts(seq INTEGER PRIMARY KEY,method TEXT,scope TEXT,key TEXT,status INTEGER);
        PRAGMA user_version=2;''')
    for service in range(2):
        r = {'service': service, 'key': '2:shared', 'payload': f'service{service}/value', 'conversation': 2, 'version': 1}
        receipt = expected_receipt(r)
        identity = {k: v for k, v in receipt.items() if k != 'count'}
        db.execute('INSERT INTO authority VALUES(?,?,?,?)', (r['service'] and 'service1' or 'service0', 2, 1, 1))
        db.execute('INSERT INTO effects VALUES(?,?,?,1)', (receipt['scope'], r['key'], json.dumps(identity)))
        db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)', (service + 1, 'POST', receipt['scope'], r['key'], 201))
    db.commit()


def attempt_fixture(admitted):
    attempts = []
    for r in admitted:
        pairs = [('GET', 404)]
        tag = r['service'], r['stage'], r['intent']
        if tag == (0, 0, 'revoke'):
            pairs += [('POST', 403)]
        elif tag not in ((1, 0, 'cancel'), (0, 1, 'live')):
            pairs += [('POST', 201)]
            if tag == (0, 1, 'post'):
                pairs += [('GET', 200)]
            if r['intent'] == 'post':
                pairs += [('POST', 200), ('POST', 409)]
        for method, status in pairs:
            attempts.append([len(attempts) + 1, method, r['scope'], r['key'], status])
    return attempts


class ScopedSavedEvidenceTests(unittest.TestCase):
    def test_equal_keys_and_numeric_ids_are_bound_to_distinct_scopes(self):
        ids = inventory()
        _, admitted, by_key = validate_inventory(ids)
        self.assertEqual(len(by_key), 12)
        left = next(r for r in admitted if r['service'] == 0 and r['intent'] == 'post')
        right = next(r for r in admitted if r['service'] == 1 and r['intent'] == 'post')
        self.assertEqual(left['key'], right['key'])
        self.assertNotEqual(expected_receipt(left), expected_receipt(right))
        for field, value in (('scope', 'service1'), ('payload', right['payload']), ('key', 'service0:encoded'), ('submissionId', True)):
            changed = copy.deepcopy(ids)
            changed['requests'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_inventory(changed)
        changed = copy.deepcopy(ids)
        changed['conversations'][1] = [3, 9]
        with self.assertRaisesRegex(AssertionError, 'repeat'):
            validate_inventory(changed)

    def test_composite_sql_returns_both_equal_keys_and_rejects_foreign_identity(self):
        with closing(sqlite3.connect(':memory:')) as db:
            effect_database(db)
            result = read_scoped_endpoint(db)
            self.assertEqual([r['scope'] for r in result['effects']], ['service0', 'service1'])
            self.assertEqual([r['key'] for r in result['effects']], ['2:shared', '2:shared'])
            identity = dict(result['effects'][0]); identity.pop('count'); identity['scope'] = 'service1'
            db.execute('UPDATE effects SET identity=? WHERE scope=?', (json.dumps(identity), 'service0'))
            with self.assertRaises(AssertionError):
                read_scoped_endpoint(db)

    def test_v2_marker_does_not_accept_legacy_key_only_or_unscoped_attempt_schema(self):
        for statement in (
            'CREATE TABLE effects(key TEXT PRIMARY KEY,identity TEXT,count INTEGER)',
            'CREATE TABLE effects(scope TEXT PRIMARY KEY,key TEXT,identity TEXT,count INTEGER)',
        ):
            with self.subTest(statement=statement), closing(sqlite3.connect(':memory:')) as db:
                db.executescript('PRAGMA user_version=2; CREATE TABLE authority(scope TEXT,conversation INTEGER,version INTEGER,allowed INTEGER,PRIMARY KEY(scope,conversation));' + statement)
                db.execute('CREATE TABLE attempts(seq INTEGER PRIMARY KEY,method TEXT,key TEXT,status INTEGER)')
                with self.assertRaises(AssertionError):
                    read_scoped_endpoint(db)
        with closing(sqlite3.connect(':memory:')) as db:
            effect_database(db); db.execute('PRAGMA user_version=1')
            with self.assertRaisesRegex(AssertionError, 'scoped-v2'):
                read_scoped_endpoint(db)

    def test_sql_effect_identity_fingerprint_count_and_typed_values_are_checked(self):
        with closing(sqlite3.connect(':memory:')) as db:
            effect_database(db)
            original = db.execute('SELECT identity FROM effects WHERE scope=?', ('service0',)).fetchone()[0]
            for field, value in (('fingerprint', '0' * 64), ('conversation', True), ('version', '1'), ('extra', 1)):
                identity = json.loads(original); identity[field] = value
                db.execute('UPDATE effects SET identity=? WHERE scope=?', (json.dumps(identity), 'service0'))
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    read_scoped_endpoint(db)
            db.execute('UPDATE effects SET identity=?,count=2 WHERE scope=?', (original, 'service0'))
            with self.assertRaises(AssertionError):
                read_scoped_endpoint(db)

    def test_immutable_copied_sql_is_re_read_and_cannot_be_replaced_by_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); stem = 'effects-stage2'
            with closing(sqlite3.connect(d / f'{stem}.sqlite')) as db:
                effect_database(db); endpoint = read_scoped_endpoint(db)
            (d / f'{stem}-endpoint.json').write_text(json.dumps(endpoint), encoding='utf-8')
            comparison = {'equal': True, 'source_endpoint_sha256': digest(endpoint), 'copy_endpoint_sha256': digest(endpoint)}
            (d / f'{stem}-copy-comparison.json').write_text(json.dumps(comparison), encoding='utf-8')
            names = {p.name for p in d.iterdir()}
            self.assertEqual(verify_copied_endpoint(d, 2), endpoint)
            self.assertEqual({p.name for p in d.iterdir()}, names)
            with closing(sqlite3.connect(d / f'{stem}.sqlite')) as db, db:
                db.execute('UPDATE attempts SET status=200 WHERE seq=1')
            with self.assertRaisesRegex(AssertionError, 'SQL differs'):
                verify_copied_endpoint(d, 2)

    def test_effect_attempts_join_scope_and_key_before_asymmetric_outcomes(self):
        _, admitted, _ = validate_inventory(inventory())
        attempts = attempt_fixture(admitted)
        validate_attempts(admitted, attempts)
        for change in ('foreign_scope', 'denied_became_created', 'recovery_reposted', 'swapped_control_status'):
            wrong = copy.deepcopy(attempts)
            if change == 'foreign_scope':
                wrong[0][2] = 'service1'
            elif change == 'denied_became_created':
                next(a for a in wrong if a[4] == 403)[4] = 201
            elif change == 'recovery_reposted':
                next(a for a in wrong if a[1:] == ['GET', 'service0', '2:s1-post', 200])[1] = 'POST'
            else:
                row = next(a for a in wrong if a[4] == 409); row[4] = 400
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate_attempts(admitted, wrong)

    def test_typed_events_filter_keyless_envelopes_before_reading_control_fields(self):
        ids = inventory(); _, admitted, _ = validate_inventory(ids)
        events = [{'type': 'ready'}, {'type': 'committed-state', 'state': {'active': {}}},
                  {'type': 'remote-authority', 'scope': 'service0'}]
        for r in admitted:
            if r['intent'] == 'post':
                common = {'stage': 2, 'service': r['service'], 'key': r['key']}
                events += [{'type': 'duplicate-effect-control', **common, 'receipt': expected_receipt(r)},
                           {'type': 'changed-effect-control', **common, 'status': 409}]
        validate_controls(ids, admitted, events)
        self.assertEqual(typed(events, 'ready'), [{'type': 'ready'}])
        wrong = copy.deepcopy(events)
        next(e for e in wrong if e['type'] == 'duplicate-effect-control')['receipt']['scope'] = 'service1'
        with self.assertRaises(AssertionError):
            validate_controls(ids, admitted, wrong)
        with self.assertRaises(AssertionError):
            typed([{'key': 'missing-type'}], 'ready')


if __name__ == '__main__':
    unittest.main()
