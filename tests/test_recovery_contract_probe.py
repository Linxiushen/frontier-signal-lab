"""Contract tests exercise traces and invariants rather than policy labels."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "experiments" / "recovery_contract_probe.py"
SPEC = importlib.util.spec_from_file_location("recovery_contract_probe", SOURCE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class RecoveryContractTests(unittest.TestCase):
    def test_pre_persistence_loss_is_never_magically_recovered(self):
        for cls in probe.PROTOCOLS:
            model = probe.replay(cls, probe.message_events(cls, crash_after=1))
            self.assertEqual(model.oracle["generated"], ["m1"])
            self.assertEqual(model.oracle["acknowledged"], [])
            self.assertEqual(model.disk["messages"], {})
            self.assertEqual(model.metrics()["acknowledged_message_loss"], 0)

    def test_naive_ack_before_durable_write_has_counterexample(self):
        model = probe.replay(probe.Protocol, probe.message_events(probe.Protocol, crash_after=2))
        self.assertEqual(model.oracle["acknowledged"], ["m1"])
        self.assertEqual(model.metrics()["acknowledged_message_loss"], 1)

    def test_durable_ack_survives_every_enumerated_message_cut(self):
        for cls in (probe.DurableLog, probe.VersionedJournal):
            for cut in range(5):
                model = probe.replay(cls, probe.message_events(cls, crash_after=cut))
                self.assertEqual(model.metrics()["acknowledged_message_loss"], 0)
                for ack in model.oracle["acknowledged"]:
                    self.assertIn(ack, model.disk["messages"])

    def test_hung_hook_blocks_naive_persistence_but_not_durable_write(self):
        naive = probe.replay(probe.Protocol, probe.message_events(probe.Protocol, hangs=True))
        durable = probe.replay(probe.DurableLog, probe.message_events(probe.DurableLog, hangs=True))
        self.assertNotIn("m1", naive.disk["messages"])
        self.assertIn("m1", durable.disk["messages"])

    def test_compaction_queues_turn_and_commits_current_version(self):
        events = dict(probe.scenarios(probe.VersionedJournal))["compaction_overlap"]
        model = probe.replay(probe.VersionedJournal, events)
        self.assertEqual(model.trace[1]["volatile"]["queued"], ["t1"])
        self.assertEqual(model.trace[2]["volatile"]["turns"], {"t1": 1})
        self.assertEqual(model.metrics()["stale_context"], 0)
        self.assertEqual(probe.replay(probe.DurableLog, events).metrics()["stale_context"], 1)

    def test_duplicate_receipt_is_idempotent_but_distinct_turn_survives(self):
        events = dict(probe.scenarios(probe.VersionedJournal))["duplicate_completion_after_restart"]
        model = probe.replay(probe.VersionedJournal, events)
        self.assertEqual(model.disk["effects"], ["child1:turn1", "child1:turn2"])
        self.assertEqual(model.metrics()["duplicate_effect"], 0)
        self.assertEqual(probe.replay(probe.DurableLog, events).metrics()["duplicate_effect"], 1)

    def test_durable_retirement_prevents_restart_resurrection(self):
        events = dict(probe.scenarios(probe.VersionedJournal))["terminal_retry_after_restart"]
        model = probe.replay(probe.VersionedJournal, events)
        self.assertEqual(model.assignments["child1:turn1"], "retired")
        self.assertEqual(model.metrics()["resurrected_retry"], 0)
        self.assertEqual(probe.replay(probe.Protocol, events).metrics()["resurrected_retry"], 1)

    def test_failure_evidence_survives_success_without_committing_failed_score(self):
        events = dict(probe.scenarios(probe.VersionedJournal))["scoring_failure_then_success"]
        model = probe.replay(probe.VersionedJournal, events)
        self.assertEqual(model.disk["failures"], [{"attempt": "a1", "diagnostics": {"reason": "timeout"}}])
        self.assertEqual(model.disk["score"], 1)
        self.assertIsNone(model.trace[2]["durable_after"]["score"])
        self.assertEqual(model.metrics()["missing_failure_evidence"], 0)
        self.assertEqual(probe.replay(probe.DurableLog, events).metrics()["missing_failure_evidence"], 1)

    def test_replay_is_deterministic_and_trace_snapshots_do_not_alias(self):
        report = probe.run_probe()
        self.assertEqual(report, probe.run_probe())
        row = report["runs"][0]
        self.assertEqual(probe.replay(probe.Protocol, row["events"]).trace, row["trace"])
        events = [{"action": "generate"}, {"action": "persist"}]
        model = probe.replay(probe.DurableLog, events)
        snapshot = copy.deepcopy(model.trace[0])
        model.disk["messages"]["later"] = "change"
        self.assertEqual(model.trace[0], snapshot)

    def test_export_includes_standalone_replayable_counterexamples(self):
        report = probe.run_probe()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            probe.write_report(report, output)
            self.assertEqual(json.loads((output / "probe.json").read_text(encoding="utf-8")), report)
            traces = list((output / "counterexamples").glob("*.json"))
            self.assertTrue(traces)
            classes = {cls.name: cls for cls in probe.PROTOCOLS}
            for path in traces:
                row = json.loads(path.read_text(encoding="utf-8"))
                model = probe.replay(classes[row["protocol"]], row["events"])
                self.assertEqual(model.metrics(), row["metrics"])


if __name__ == "__main__":
    unittest.main()
