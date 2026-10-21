"""Pre-freeze schema controls; mocked native calls and archived bytes only.

Replaying v2 with the new auditor is a regression fixture, never a retroactive
upgrade of v2's frozen acceptance. No child, backend or model is started here.
"""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from experiments import observed_job_probe_v2 as engine
from experiments import observed_job_probe_v3 as probe
from experiments.observed_job_probe import FileSink
from experiments.trace_ledger import LedgerIOError, LedgerLimitError
from scripts import audit_observed_job_v2 as old_auditor
from scripts import audit_observed_job_v3 as auditor
from tests.test_observed_job import fixture as adapter_fixture
from tests.test_observed_job_v2 import fixture as inventory_fixture

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "results/observed-job-v2/raw"
OLD_PROTOCOL = ROOT / "fixtures/observed-job-v2/protocol.json"
OLD_FREEZE = ROOT / "fixtures/observed-job-v2/implementation.json"


class SchemaControls(unittest.TestCase):
    def setUp(self):
        for target in ("WindowsBackend",):
            patch = mock.patch.object(engine.native, target,
                side_effect=AssertionError("No native backend in schema tests"))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(engine.subprocess, "Popen",
            side_effect=AssertionError("No child in schema tests"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_wrapper_reuses_original_case_without_forking_producer(self):
        self.assertIs(probe.run_case, engine.run_case)
        self.assertEqual(probe.SOURCES[:len(engine.SOURCES)], engine.SOURCES)

    def test_real_adapter_file_sink_capacity_and_partial_serialization(self):
        for partial in (False, True):
            with self.subTest(partial=partial):
                stream = io.BytesIO()
                sink = FileSink(stream, partial)
                session, job, _ = adapter_fixture(sink,
                    max_rows=64 if partial else 1)
                ref = session.start(["mock.exe"])
                with self.assertRaises(LedgerIOError if partial else LedgerLimitError):
                    session.sample("rejected-sample")
                raw = stream.getvalue()
                self.assertEqual(raw.split(b"\n", 1)[1], b'{"emi' if partial else b'')
                writes = sink.writes
                with self.assertRaises(engine.native.ObserverError):
                    session.sample("forbidden-retry")
                result = session.shutdown()
                self.assertEqual(stream.getvalue(), raw)
                self.assertEqual(sink.writes, writes)
                case = {"name": "partial_write" if partial else "row_cap",
                    "worker_ref": {"pid": ref.pid, "creation_filetime": ref.creation_filetime},
                    "shutdown": result, "write_calls": writes,
                    "expected_error": "LedgerIOError" if partial else "LedgerLimitError",
                    "later_sampling_refused": True}
                auditor.audit_trace(raw, case, {})
                job.terminate.assert_called_once()
                job.close.assert_called_once()
                job.close_refs.assert_called_once()
                if partial:
                    with self.assertRaises(AssertionError):
                        old_auditor.audit_trace(raw, case, {})
                    for tail in (b'{"kin', b'', b'{"emiX'):
                        with self.subTest(tail=tail), self.assertRaises(AssertionError):
                            auditor.audit_trace(raw[:-5] + tail, case, {})
                    changed = copy.deepcopy(case)
                    changed["shutdown"]["ledger"]["failure"]["sink_may_have_uncommitted_bytes"] = False
                    with self.assertRaises(AssertionError):
                        auditor.audit_trace(raw, changed, {})

    def topology(self):
        row, case, paths, hashes, freeze = inventory_fixture()
        helper = copy.deepcopy(row["processes"][0])
        helper.update(pid=12, parent_pid=10, creation_filetime=102,
            approved_known=False, policy_role="unapproved")
        console = copy.deepcopy(row["processes"][1])
        console.update(pid=13, parent_pid=12, creation_filetime=103)
        row["processes"].extend([helper, console])
        row.update(observed_pids=[10, 11, 12, 13], job_count_before=4,
            job_count_after=4, unapproved_pids=[11, 12, 13])
        case["helper_ready"] = {"pid": 12, "creation_filetime": 102}
        return row, case, paths, hashes, freeze

    def test_four_node_helper_console_is_audited_and_both_extras_denied(self):
        row, case, paths, hashes, freeze = self.topology()
        identities, pin = auditor.audit_inventory(row, case, freeze, True)
        self.assertEqual(identities, {(10, 100), (11, 101), (12, 102), (13, 103)})
        result = engine.decide(row, case["worker_ref"], case["parent_pid"], paths, hashes, pin)
        self.assertFalse(result["admitted"])
        self.assertEqual(result["rejected_pids"], [12, 13])
        self.assertEqual(result["errors"], ["unregistered_process_identity"])
        with self.assertRaises(AssertionError):
            old_auditor.audit_inventory(row, case, freeze, True)

    def test_helper_console_identity_parent_image_and_membership_mutations(self):
        row, case, _, _, freeze = self.topology()
        changes = [lambda n: n.update(parent_pid=999),
            lambda n: n.update(parent_pid=10),
            lambda n: n.update(creation_filetime=101),
            lambda n: n.update(job_member=False),
            lambda n: n.update(alive=False),
            lambda n: n.update(approved_known=True),
            lambda n: n["image"].update(sha256="c" * 64),
            lambda n: n["image"].update(normalized_path_sha256="c" * 64),
            lambda n: n["image"].update(retained_identity_stable=False),
            lambda n: n["image"].update(exact_path_matches=[])]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                changed = copy.deepcopy(row)
                change(changed["processes"][-1])
                with self.assertRaises(AssertionError):
                    auditor.audit_inventory(changed, case, freeze, True)

    def test_archived_v2_all_case_bytes_exercise_new_schema_only(self):
        result = auditor.audit(ARCHIVE, OLD_PROTOCOL, OLD_FREEZE, ROOT)
        self.assertEqual((result["cases"], result["retained_exits"], result["committed_rows"]), (4, 10, 38))
        with self.assertRaises(AssertionError):
            old_auditor.audit(ARCHIVE, OLD_PROTOCOL, OLD_FREEZE, ROOT)

    def test_full_saved_report_requires_rejection_of_helper_console_too(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "archived-fixture"
            shutil.copytree(ARCHIVE, output)
            report = json.loads((output / "report.json").read_bytes())
            case = report["cases"][-1]
            case["decisions"][-1]["rejected_pids"] = [case["helper_ready"]["pid"]]
            (output / "report.json").write_text(json.dumps(report), encoding="utf8")
            (output / case["name"] / "result.json").write_text(json.dumps(case), encoding="utf8")
            with self.assertRaises(AssertionError):
                auditor.audit(output, OLD_PROTOCOL, OLD_FREEZE, ROOT)


if __name__ == "__main__":
    unittest.main()
