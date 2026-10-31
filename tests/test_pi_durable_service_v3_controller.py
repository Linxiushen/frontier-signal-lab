"""Post-outcome v3 serialization regression; never runs native Pi tasks."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'pi_recovery_v3', ROOT / 'scripts/run_pi_durable_recovery_v3.py')
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)

# Exact columns/types/check constraints from the retained Pi1.4.0 native schema.
SCHEMA = '''
CREATE TABLE documents (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
 family INTEGER NOT NULL CHECK (family IN (0, 1)), key_value TEXT NOT NULL,
 scope_kind TEXT NOT NULL CHECK (scope_kind IN ('session','conversation','task')),
 owner_id INTEGER NOT NULL, created_at INTEGER NOT NULL, retired_at INTEGER,
 record TEXT NOT NULL CHECK (json_valid(record))) STRICT;
CREATE TABLE document_revisions (
 document_id INTEGER NOT NULL, seq INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK (kind IN ('base','delta')), version INTEGER NOT NULL,
 content TEXT NOT NULL CHECK (json_valid(content)),
 PRIMARY KEY (document_id,seq)) STRICT;
'''

class PiDurableV3ControllerTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript(SCHEMA)

    def add_document(self, kind, ident=1):
        self.db.execute('INSERT INTO documents VALUES(?,?,0,?, ?,1,1,NULL,?)',
                        (ident, kind, 'null', 'session', '{}'))

    def test_native_json_serialized_kind_and_latest_endpoint(self):
        self.add_document(json.dumps('frontier.service'))
        for seq in (3, 8):
            self.db.execute('INSERT INTO document_revisions VALUES(?,?,?,1,?)',
                            (1, seq, 'base', json.dumps({'seq': seq})))
        self.assertIsNone(self.db.execute(
            "SELECT id FROM documents WHERE kind='frontier.service'").fetchone())
        self.assertEqual(controller.read_service_document(self.db),
                         ({'seq': 8}, [3, 8]))

    def test_empty_document_set_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            controller.read_service_document(self.db)

    def test_wrong_kind_rejected(self):
        for kind in ('frontier.service', json.dumps('other.service')):
            with self.subTest(kind=kind):
                self.db.execute('DELETE FROM documents')
                self.add_document(kind)
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    controller.read_service_document(self.db)

    def test_missing_revision_rejected(self):
        self.add_document(json.dumps('frontier.service'))
        with self.assertRaisesRegex(ValueError, 'Missing'):
            controller.read_service_document(self.db)

    def test_multiple_service_documents_rejected(self):
        self.add_document(json.dumps('frontier.service'), 1)
        self.add_document(json.dumps('frontier.service'), 2)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            controller.read_service_document(self.db)

    def test_old_freeze_refused_before_protocol_or_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old-freeze.json'
            path.write_text(json.dumps({'source_sha256': {
                'scripts/run_pi_durable_recovery_v2.py': 'old'}}), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'own exact source hash'):
                controller.execute(path)

if __name__ == '__main__':
    unittest.main()
