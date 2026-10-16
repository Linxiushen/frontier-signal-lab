"""Pure synthetic receipt and mutation tests; no child process or OS calls."""
import copy
import datetime as dt
import unittest

from scripts import audit_process_observer as auditor

MIB = 1024 * 1024


def fixture():
    """Construct public-shaped receipts independently of the observer implementation."""
    sources = {p: "a" * 64 for p in auditor.SOURCE_PATHS}
    protocol = {"schema_version": 1, "experiment_id": "windows-interpreter-observer-engineering-v1",
                "predeclared_at": "2026-10-16T00:00:00+00:00", "config": dict(auditor.CONFIG),
                "source_paths": list(auditor.SOURCE_PATHS),
                "cases_in_order": [{"id": i, "allocation_bytes": n, "mode": m} for i, n, m in auditor.CASES]}
    freeze = {"protocol_sha256": "b" * 64, "new_source_files_sha256": sources,
              "python_executable_sha256": "c" * 64, "frozen_at": "2026-10-16T00:00:01+00:00"}
    report = {"schema_version": 1, "experiment_id": protocol["experiment_id"], "passed": True,
              "protocol_sha256": "b" * 64, "implementation_sha256": "d" * 64,
              "source_sha256": dict(sources), "launch_executable_sha256": "c" * 64,
              "protocol_predeclared_at": protocol["predeclared_at"], "implementation_frozen_at": freeze["frozen_at"],
              "started_at": "2026-10-16T00:00:02+00:00", "completed_at": "2026-10-16T00:00:53+00:00",
              "wall_seconds": 51.0, "os_name": "nt", "no_fallback": True, "cases": []}
    for index, (case_id, allocation, mode) in enumerate(auditor.CASES):
        base = 100.0 + index * 10
        offset = 1000 * index
        nonce, desc_nonce = f"{2 * index + 1:064x}", f"{2 * index + 2:064x}"
        def reading(clock, allocated=False, pid=offset + 2, creation=20):
            return {"pid": pid, "creation_filetime": creation, "perf_counter": clock,
                    "memory": {"resident_bytes": 12 * MIB + (allocation if allocated else 0),
                               "private_bytes": 8 * MIB + (allocation if allocated else 0),
                               "peak_resident_bytes": 12 * MIB + (allocation if allocated else 0)}}
        ready = {**reading(base), "nonce": nonce, "role": "worker", "parent_pid": offset + 1,
                 "runtime_executable_basename": "python.exe", "runtime_executable_sha256": "e" * 64}
        desc = {**reading(base, pid=offset + 4, creation=40), "nonce": desc_nonce, "role": "descendant",
                "parent_pid": offset + 3, "runtime_executable_basename": "python.exe", "runtime_executable_sha256": "e" * 64}
        def ancestor(pid, creation, parent):
            return {"pid": offset + pid, "creation_filetime": creation, "parent_pid": offset + parent, "job_member": True}
        start = dt.datetime(2026, 10, 16, 0, 0, 3 + 10 * index, tzinfo=dt.timezone.utc)
        case = {"id": case_id, "expected_explicit_allocation_bytes": allocation, "mode": mode, "passed": True,
                "nonce": nonce, "descendant_nonce": desc_nonce, "started_at": start.isoformat(),
                "completed_at": (start + dt.timedelta(seconds=5)).isoformat(), "wall_seconds": 5.0,
                "launcher": {"pid": offset + 1, "creation_filetime": 10, "assigned_while_suspended": True, "job_handle_inherited": False},
                "worker_identity": {"self_receipt": ready, "verified_ancestry": [ancestor(2, 20, 1), ancestor(1, 10, 900)], "launcher_differs_from_interpreter": True},
                "descendant_identity": {"self_receipt": desc, "verified_ancestry": [ancestor(4, 40, 3), ancestor(3, 30, 2), ancestor(2, 20, 1)], "launcher_pid": offset + 3, "actual_pid": offset + 4},
                "samples": [], "memory_brackets": {}, "termination_path": None}
        for stage, tick in (("baseline", base + 1), ("allocated", base + 2)):
            before, parent, after = [reading(tick + x, stage == "allocated") for x in (0, 0.1, 0.2)]
            before.update(nonce=nonce, role="worker")
            after.update(nonce=nonce, role="worker")
            case["samples"].append(parent)
            case["memory_brackets"][stage] = {"self_before": before, "parent": parent, "self_after": after,
                "comparison": {"same_identity": True, "ordered_monotonic_bracket": True,
                               "resident_within_tolerance": True, "private_within_tolerance": True, "passed": True}}
        minimum = {0: 0, 33554432: 25165824, 67108864: 58720256}[allocation]
        case["allocation_check"] = {"explicit_allocation_bytes": allocation,
            "parent_deltas_bytes": {"resident_bytes": allocation, "private_bytes": allocation},
            "minimum_required_increase_bytes": minimum, "passed": True}
        cleanup_start = base + 4.1
        if mode == "healthy":
            case["enforcement_reason"] = "normal_completion"
            case["healthy_completion"] = {"nonce": nonce, "role": "worker", "pid": offset + 2,
                "explicit_allocation_bytes": allocation, "descendant_launcher_returncode": 0}
        elif mode == "private_cap":
            case.update(actual_interpreter_private_limit_bytes=56 * MIB, cap_is_sampled_not_kernel_hard_ceiling=True,
                first_over_limit_sample=case["samples"][-1], enforcement_reason="memory_private_limit", termination_path="TerminateJobObject",
                termination_request_started_perf_counter=base + 2.3, termination_request_returned_perf_counter=base + 2.31,
                allocation_ready_to_termination_seconds=0.31)
        else:
            case["stalled_receipt"] = {"nonce": nonce, "role": "worker", "pid": offset + 2, "perf_counter": base + 2.3}
            if mode == "timeout":
                case.update(timeout_control_started_perf_counter=base + 2.4, timeout_control_completed_perf_counter=base + 4,
                    timeout_deadline_perf_counter=base + 3.9, timeout_wait_seconds=1.6, termination_request_started_perf_counter=base + 4.01,
                    termination_request_returned_perf_counter=base + 4.02, enforcement_reason="timeout", termination_path="TerminateJobObject")
            else:
                case.update(enforcement_reason="explicit_job_handle_close_control", termination_path="KILL_ON_JOB_CLOSE; no TerminateJobObject",
                    job_close_started_perf_counter=base + 2.4, job_close_returned_perf_counter=base + 2.5)
        case["cleanup"] = {"all_retained_handles_exited": True, "job_active_count": None if mode == "job_close" else 0,
            "exit_codes": [{"pid": offset + pid, "creation_filetime": created, "exit_code": 0 if mode == "healthy" else 0xE003}
                           for pid, created in ((1, 10), (2, 20), (3, 30), (4, 40))],
            "started_perf_counter": cleanup_start, "completed_perf_counter": cleanup_start + 0.1, "wall_seconds": 0.1, "timeout_seconds": 4.0}
        if mode == "job_close":
            case["cleanup"]["job_active_count_after_close_not_queryable"] = True
        report["cases"].append(case)
    return report, protocol, freeze, sources


class ReceiptAuditTests(unittest.TestCase):
    def run_audit(self, data):
        report, protocol, freeze, sources = data
        return auditor.audit(report, protocol, freeze, protocol_sha256="b" * 64, freeze_sha256="d" * 64,
                             actual_source_sha256=sources, launch_sha256="c" * 64)

    def test_complete_synthetic_receipt(self):
        result = self.run_audit(fixture())
        self.assertTrue(result["passed"], result["failures"])
        self.assertGreater(result["check_count"], 400)
        self.assertIn("no OS remeasurement", result["scope"])

    def rejects(self, mutate, fragment):
        data = fixture()
        mutate(data)
        result = self.run_audit(data)
        self.assertFalse(result["passed"])
        self.assertTrue(any(fragment in f for f in result["failures"]), result["failures"])

    def test_identity_nonce_and_ancestry_tamper(self):
        mutations = [
            (lambda d: d[0]["cases"][0]["worker_identity"]["self_receipt"].update(nonce="f" * 64), "nonce_role"),
            (lambda d: d[0]["cases"][0]["worker_identity"]["verified_ancestry"][0].update(parent_pid=99999), "parent_creation_order"),
            (lambda d: d[0]["cases"][0]["descendant_identity"]["verified_ancestry"][1].update(creation_filetime=50), "parent_creation_order"),
            (lambda d: d[0]["cases"][0]["samples"][0].update(pid=1), "actual_interpreter_identity"),
        ]
        for mutation, fragment in mutations:
            with self.subTest(fragment=fragment):
                self.rejects(mutation, fragment)

    def test_bracket_and_allocation_tamper(self):
        self.rejects(lambda d: d[0]["cases"][0]["memory_brackets"]["allocated"]["self_after"].update(perf_counter=0), "independent_bracket_recalculation")
        self.rejects(lambda d: d[0]["cases"][0]["allocation_check"]["parent_deltas_bytes"].update(private_bytes=0), "independent_allocation_delta")

    def test_cap_crossing_and_return_timing_tamper(self):
        self.rejects(lambda d: d[0]["cases"][2].update(actual_interpreter_private_limit_bytes=100 * MIB), "sampled_private_limit")
        self.rejects(lambda d: d[0]["cases"][2].update(first_over_limit_sample=copy.deepcopy(d[0]["cases"][2]["samples"][0])), "first_cap_crossing")
        self.rejects(lambda d: d[0]["cases"][2].update(termination_request_returned_perf_counter=124, allocation_ready_to_termination_seconds=2.0), "within_1s")

    def test_early_timeout_and_cleanup_tamper(self):
        self.rejects(lambda d: d[0]["cases"][3].update(timeout_control_completed_perf_counter=133, timeout_wait_seconds=0.6), "no_early_1point5s_timeout")
        self.rejects(lambda d: d[0]["cases"][3]["cleanup"].update(job_active_count=1), "job_active_zero")
        self.rejects(lambda d: d[0]["cases"][3]["cleanup"].update(completed_perf_counter=140), "cleanup_within_4s")

    def test_exit_status_missing_handle_and_closed_job_tamper(self):
        self.rejects(lambda d: d[0]["cases"][0]["cleanup"]["exit_codes"][0].update(exit_code=1), "healthy_all_exit_zero")
        self.rejects(lambda d: d[0]["cases"][1]["cleanup"]["exit_codes"].pop(), "all_retained_identities")
        self.rejects(lambda d: d[0]["cases"][4]["cleanup"].update(job_active_count=0), "closed_job_count_unqueryable")

    def test_freeze_source_and_declared_protocol_tamper(self):
        self.rejects(lambda d: d[2].update(protocol_sha256="f" * 64), "protocol_file_hash")
        self.rejects(lambda d: d[3].update({auditor.SOURCE_PATHS[0]: "f" * 64}), "actual_source_file_hashes")
        self.rejects(lambda d: d[1]["config"].update(timeout_control_seconds=0.1), "frozen_numeric_protocol")

    def test_failed_and_partial_runs_are_auditable_but_fail(self):
        data = fixture()
        data[0].update(passed=False, error="deliberate infrastructure failure")
        data[0]["cases"][1] = {"id": "healthy64", "passed": False, "error": "failure"}
        result = self.run_audit(data)
        self.assertFalse(result["passed"])
        self.assertIn("declared_acceptance_passed", result["failures"])
        self.assertTrue(any("incomplete_or_invalid_receipt" in f for f in result["failures"]))
        self.assertTrue(any(c["check"].startswith("job_close_descendant:") for c in result["checks"]))


if __name__ == "__main__":
    unittest.main()
