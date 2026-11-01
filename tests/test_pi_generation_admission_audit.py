import copy
import hashlib
import json
import sqlite3
import unittest
from experiments.pi_generation_admission_audit import read_endpoint, validate_gap_snapshot

class AdmissionSavedTests(unittest.TestCase):
    def rows(self, intent):
        r={'key':'c:r','conversation':'c','requestId':'r','payload':'p','version':1,'intent':intent,'submissionId':10}
        h={k:r[k] for k in ('conversation','requestId','payload','version')}
        h['fingerprint']=hashlib.sha256(b'p').hexdigest()
        n=[] if intent=='reserve-gap' else [{'id':10,'conversationId':'c','requestId':'r'}]
        e={} if intent=='reserve-gap' else {'c:r':{'count':1,'payload':'p'}}
        if intent=='recover': h['submissionId']=10
        return r,h,n,e
    def test_exact_reservation_submit_and_link_gaps(self):
        for intent in ('reserve-gap','submit-gap','recover'):
            validate_gap_snapshot(*self.rows(intent))
    def test_wrong_gap_native_or_extra_host_link_is_rejected(self):
        for intent in ('reserve-gap','submit-gap'):
            args=self.rows(intent);args[1]['submissionId']=10
            with self.assertRaises(AssertionError):validate_gap_snapshot(*args)
        for field in ('conversation','requestId','payload','version','fingerprint'):
            args=self.rows('reserve-gap');args[1][field]='wrong'
            with self.assertRaises(AssertionError):validate_gap_snapshot(*args)
        args=self.rows('reserve-gap');args[2].append({'id':10})
        with self.assertRaises(AssertionError):validate_gap_snapshot(*args)
        args=self.rows('submit-gap');args[2].append(copy.deepcopy(args[2][0]))
        with self.assertRaises(AssertionError):validate_gap_snapshot(*args)
    def test_duplicate_effect_and_terminal_reservation_rejected(self):
        args=self.rows('submit-gap');args[3]['c:r']['count']=2
        with self.assertRaises(AssertionError):validate_gap_snapshot(*args)
        for flag in ('terminal','cancelled'):
            args=self.rows('reserve-gap');args[1][flag]=True
            with self.assertRaises(AssertionError):validate_gap_snapshot(*args)
    def test_native_encoded_kind_and_full_tables(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript('CREATE TABLE documents(id INTEGER,kind TEXT);CREATE TABLE document_revisions(document_id INTEGER,seq INTEGER,content TEXT);')
            for t in ('tasks','entries','submissions','conversations'):db.execute('CREATE TABLE '+t+'(id INTEGER,record TEXT)')
            db.execute('INSERT INTO documents VALUES(1,?)',(json.dumps('frontier.generation-admission-service'),))
            db.execute('INSERT INTO document_revisions VALUES(1,2,?)',(json.dumps({'active':{}}),))
            self.assertEqual(read_endpoint(db),{'state':{'active':{}},'document_sequences':[2],'tasks':[],'entries':[],'submissions':[],'conversations':[]})
            db.execute('UPDATE documents SET kind=?',('frontier.generation-admission-service',))
            with self.assertRaises(AssertionError):read_endpoint(db)
