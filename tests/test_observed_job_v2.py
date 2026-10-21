"""Pure admission and independent-auditor mutations; never launch a process."""
import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from experiments import observed_job_probe_v2 as probe
from scripts.audit_observed_job_v2 import audit_inventory, audit_trace


def fixture():
    paths = {"worker": Path("python.exe"), "conhost": Path("conhost.exe")}
    hashes = {"worker": "a" * 64, "conhost": "b" * 64}
    nodes = []
    for pid, parent, role, creation in [(10, 1, "worker", 100), (11, 10, "conhost", 101)]:
        nodes.append({"pid": pid, "parent_pid": parent, "creation_filetime": creation,
            "job_member": True, "alive": True, "approved_known": role == "worker", "policy_role": role if role == "worker" else "unapproved",
            "image": {"basename": paths[role].name, "sha256": hashes[role],
                "normalized_path_sha256": probe.dual.path_hash(paths[role]), "exact_path_matches": [role],
                "queried_from_retained_handle": True, "retained_identity_stable": True}})
    row = {"label": "mock", "census_complete": True, "errors": [], "processes": nodes,
        "observed_pids": [10, 11], "job_count_before": 2, "job_count_after": 2,
        "truncated": False, "query_budget_exceeded": False, "all_known_present": True,
        "job_count_matches_before": True, "job_count_matches_after": True,
        "started_perf_counter": 1.0, "completed_perf_counter": 1.25, "wall_seconds": .25,
        "unapproved_pids": [11]}
    case = {"worker_ref": {"pid": 10, "creation_filetime": 100}, "parent_pid": 1}
    freeze = {"worker_basename": "python.exe", "executables_sha256": hashes,
        "executable_path_sha256": {k: probe.dual.path_hash(p) for k, p in paths.items()}}
    return row, case, paths, hashes, freeze


class DirectJobPolicyTests(unittest.TestCase):
    def setUp(self):
        self.guards = [mock.patch.object(probe.native, "WindowsBackend", side_effect=AssertionError("No OS work in tests")),
            mock.patch.object(probe.subprocess, "Popen", side_effect=AssertionError("No child in tests"))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)

    def decide(self, row, case, paths, hashes, pin=None):
        return probe.decide(row, case["worker_ref"], case["parent_pid"], paths, hashes, pin)

    def test_exact_retained_topology_admits_and_audits(self):
        row, case, paths, hashes, freeze = fixture()
        result = self.decide(row, case, paths, hashes)
        self.assertTrue(result["admitted"])
        identities, pin = audit_inventory(row, case, freeze)
        self.assertEqual(identities, {(10, 100), (11, 101)})
        self.assertEqual(pin, result["pin"])
        self.assertTrue(self.decide(row, case, paths, hashes, pin)["admitted"])

    def test_unregistered_same_image_does_not_register_a_pid(self):
        row, case, paths, hashes, freeze = fixture()
        extra = copy.deepcopy(row["processes"][0])
        extra.update(pid=12, parent_pid=10, creation_filetime=102, approved_known=False, policy_role="unapproved")
        row["processes"].append(extra)
        row.update(observed_pids=[10, 11, 12], job_count_before=3, job_count_after=3, unapproved_pids=[11, 12])
        case["helper_ready"] = {"pid": 12, "creation_filetime": 102}
        result = self.decide(row, case, paths, hashes)
        self.assertFalse(result["admitted"])
        self.assertEqual(result["rejected_pids"], [12])
        audit_inventory(row, case, freeze, helper=True)

    def test_native_image_handle_path_membership_and_parent_mutations_refuse(self):
        original, case, paths, hashes, freeze = fixture()
        mutations = [
            lambda n: n.update(parent_pid=999),
            lambda n: n.update(creation_filetime=99),
            lambda n: n.update(job_member=False),
            lambda n: n.update(alive=False),
            lambda n: n.update(error="query failure"),
            lambda n: n["image"].update(sha256="c" * 64),
            lambda n: n["image"].update(normalized_path_sha256="c" * 64),
            lambda n: n["image"].update(exact_path_matches=[]),
            lambda n: n["image"].update(queried_from_retained_handle=False),
            lambda n: n["image"].update(retained_identity_stable=False),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                row = copy.deepcopy(original)
                mutate(row["processes"][1])
                self.assertFalse(self.decide(row, case, paths, hashes)["admitted"])
                with self.assertRaises(AssertionError):
                    audit_inventory(row, case, freeze)

    def test_replaced_auxiliary_cannot_satisfy_existing_pin(self):
        row, case, paths, hashes, _ = fixture()
        pin = self.decide(row, case, paths, hashes)["pin"]
        row["processes"][1]["creation_filetime"] += 1
        result = self.decide(row, case, paths, hashes, pin)
        self.assertFalse(result["admitted"])
        self.assertIn("console_identity_replaced", result["errors"])
        self.assertEqual(pin["auxiliary"]["creation_filetime"], 101)

    def test_missing_duplicate_or_incomplete_inventory_refuses(self):
        original, case, paths, hashes, freeze = fixture()
        changes = [lambda r: r.update(census_complete=False), lambda r: r.update(errors=["native failure"]),
            lambda r: r.update(job_count_before=3), lambda r: r.update(observed_pids=[10]),
            lambda r: r["processes"].append(copy.deepcopy(r["processes"][1])),
            lambda r: r["processes"].pop()]
        for index, mutate in enumerate(changes):
            with self.subTest(mutation=index):
                row = copy.deepcopy(original)
                mutate(row)
                self.assertFalse(self.decide(row, case, paths, hashes)["admitted"])
                with self.assertRaises(AssertionError):
                    audit_inventory(row, case, freeze)

    def test_parent_worker_identity_must_be_exact(self):
        row, case, paths, hashes, freeze = fixture()
        for key, value in [("creation_filetime", 103), ("parent_pid", 2), ("approved_known", False)]:
            with self.subTest(key=key):
                changed = copy.deepcopy(row)
                changed["processes"][0][key] = value
                self.assertFalse(self.decide(changed, case, paths, hashes)["admitted"])
                with self.assertRaises(AssertionError):
                    audit_inventory(changed, case, freeze)

    def test_trace_auditor_rejects_missing_duplicate_wrong_identity_and_tail(self):
        protocol = {"sampler_threads": 2, "samples_per_thread": 2, "healthy_expected_rows": 6}
        rows = [{"kind": "started", "seq": 0, "pid": 10, "creation_filetime": 100,
            "emitted_perf_counter": 1.0, "native_thread_id": 1}]
        for worker in range(2):
            for index in range(2):
                rows.append({"kind": "sample", "seq": len(rows), "request_id": f"{worker}:{index}",
                    "native_thread_id": 20 + worker, "emitted_perf_counter": 2.1,
                    "reading": {"pid": 10, "creation_filetime": 100, "perf_counter": 2.0,
                        "memory": {"backend": "Windows GetProcessMemoryInfo", "resident_bytes": 1,
                            "private_bytes": 2, "peak_resident_bytes": 3}}})
        rows.append({"kind": "closed", "seq": 5, "cleanup": {"job_active_count": 0},
            "emitted_perf_counter": 3.0, "native_thread_id": 1})
        def encode(value):
            return b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode() for r in value)
        case = {"name": "threaded_samples", "worker_ref": {"pid": 10, "creation_filetime": 100},
            "sampler_native_thread_ids": [20, 21], "write_calls": 6,
            "censuses": [{"completed_perf_counter": 1.5}, {"started_perf_counter": 2.5}],
            "shutdown": {"trace_complete": True, "trace_error": None, "native_cleanup": {"job_active_count": 0},
                "ledger": {"records": rows, "committed_rows": 6, "committed_bytes": len(encode(rows)), "failure": None, "poisoned": False}}}
        audit_trace(encode(rows), case, protocol)
        for mutation in [lambda rs: rs[1].update(request_id="duplicate"),
            lambda rs: rs[2].update(request_id="0:0"),
            lambda rs: rs[1]["reading"].update(pid=999),
            lambda rs: rs[1].update(native_thread_id=1),
            lambda rs: rs[1].update(seq=7),
            lambda rs: rs[1]["reading"].update(perf_counter=1.1),
            lambda rs: rs[-1].update(cleanup={"job_active_count": 1})]:
            changed = copy.deepcopy(case)
            changed_rows = changed["shutdown"]["ledger"]["records"]
            mutation(changed_rows)
            raw = encode(changed_rows)
            changed["shutdown"]["ledger"]["committed_bytes"] = len(raw)
            with self.assertRaises(AssertionError):
                audit_trace(raw, changed, protocol)
        with self.assertRaises(AssertionError):
            audit_trace(encode(rows) + b"tail", case, protocol)


if __name__ == "__main__":
    unittest.main()
