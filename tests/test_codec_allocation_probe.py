"""Pure custody/metadata tests; no Torch import or real process is permitted."""
import builtins
from contextlib import nullcontext
import copy
import datetime as dt
import gc
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import weakref

from experiments import codec_allocation_probe as probe


class CodecAllocationProtocolTests(unittest.TestCase):
    def test_import_has_no_ml_or_process_side_effect(self):
        original = builtins.__import__
        def denied(name, *args, **kwargs):
            if name.split(".")[0] in ("torch", "transformers", "numpy"):
                raise AssertionError("ML package import during pure module import")
            return original(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=denied), \
                mock.patch.object(probe.obs, "WindowsJob", side_effect=AssertionError("process creation")):
            importlib.reload(probe)
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("transformers", sys.modules)

    def test_literal_order_protocol_and_scope_cannot_be_rescued(self):
        protocol = probe.protocol_template("2026-10-17T20:00:00+00:00")
        self.assertEqual([(r["observer_enabled"], r["method"]) for r in probe.CASES],
                         [(enabled, method) for enabled in (False, True) for method in ("dense", "int8", "int8", "dense")])
        self.assertIs(probe.validate_protocol(protocol), protocol)
        for mutate in (lambda p: p["config"].update(seed=701),
                       lambda p: p["cases_in_order"].reverse(),
                       lambda p: p["training"].update(expected_outer_saves=19),
                       lambda p: p["saved_receipt_rejection_controls"].pop()):
            changed = copy.deepcopy(protocol)
            mutate(changed)
            with self.assertRaises(probe.obs.ObserverError):
                probe.validate_protocol(changed)
        self.assertEqual(protocol["training"]["expected_outer_saves"], 33)
        self.assertEqual(protocol["training"]["expected_outer_eligible_saves"], 19)

    def test_existing_output_rejected_without_spawning(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(probe, "validate_freeze", return_value=({}, {})), \
                mock.patch.object(probe, "run_case", side_effect=AssertionError("spawned")):
            with self.assertRaises(FileExistsError):
                probe.acceptance({}, None, None, None, None, None, Path(directory))

    def test_nonrenewable_budget_reserves_cleanup(self):
        with mock.patch.object(probe.time, "perf_counter", return_value=10):
            self.assertEqual(probe.budget(5, 20, 18), 14)
            with self.assertRaises(probe.obs.ObserverError):
                probe.budget(5, 14, 30)

    def test_ack_is_exact_and_finite_and_within_original_deadline(self):
        expected = {"emitted_perf_counter": 10.0, "control_index": 0}
        accepted = dict(pid=5, filename="preimport-continue.json", control_envelope=expected,
                        next_control_index=1, accepted_perf_counter=11.0)
        waited = {"started_perf_counter": 10.1, "completed_perf_counter": 12.0}
        args = (expected, 5, "preimport-continue.json", 0, waited, 20.0, 30.0)
        self.assertTrue(probe.validate_acceptance(accepted, *args))
        for fields in ({"accepted_perf_counter": float("nan")}, {"accepted_perf_counter": 9.0},
                       {"accepted_perf_counter": 21.0}, {"next_control_index": True},
                       {"control_envelope": dict(expected, control_index=1)}, {"pid": 6}):
            self.assertFalse(probe.validate_acceptance(dict(accepted, **fields), *args))

    def test_cleanup_requires_exact_census_identity_set(self):
        rows = [{"pid": 1, "creation_filetime": 101}, {"pid": 2, "creation_filetime": 102}]
        report = {"censuses": [{"processes": rows}], "cleanup": {"all_retained_handles_exited": True,
            "job_active_count": 0, "exit_codes": [dict(row, exit_code=0) for row in rows]}}
        probe.verify_cleanup(report)
        self.assertTrue(report["cleanup_exact_retained_identity_set"])
        report["cleanup"]["exit_codes"][1]["creation_filetime"] += 1
        with self.assertRaises(probe.obs.ObserverError):
            probe.verify_cleanup(report)

    def test_json_and_directory_byte_bounds_fail_before_write(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(probe.CONFIG, maximum_json_file_bytes=20), \
                mock.patch.object(probe.obs, "write_new", side_effect=AssertionError("write attempted")):
            with self.assertRaises(probe.obs.ObserverError):
                probe.write_bounded(Path(directory) / "oversized.json", {"x": "x" * 100})

    def test_off_worker_constructs_neither_profiler_nor_weak_registry(self):
        spec = probe.case_spec("01_off_dense")
        fake_torch = mock.Mock()
        fake_torch.__version__ = "fake-pure-test"
        fake_transformers = mock.Mock()
        fake_transformers.__version__ = "fake-pure-test"
        fake_model = mock.Mock()
        info = {"initial_parameter_sha256": "a" * 64}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(probe.obs, "WindowsBackend"), \
                mock.patch.object(probe.prior, "LocalProviderGuard"), \
                mock.patch.object(probe.dual, "publish_identity"), \
                mock.patch.object(probe, "held_stage"), \
                mock.patch.object(probe, "require_control"), \
                mock.patch.object(probe, "write_bounded"), \
                mock.patch.object(probe.obs, "sha256_file", return_value="f" * 64), \
                mock.patch.object(probe, "prepare", return_value=(fake_model, object(), info)), \
                mock.patch.object(probe, "perform_study", return_value={}) as study, \
                mock.patch.object(probe.cost, "parameter_hash", return_value="a" * 64), \
                mock.patch.object(probe.prior, "import_packages", return_value=(fake_torch, fake_transformers)), \
                mock.patch.object(probe, "LifetimeRegistry", side_effect=AssertionError("OFF registry")), \
                mock.patch.object(probe, "finalize_trace", side_effect=AssertionError("OFF finalizer")):
            probe.worker(Path(directory), "a" * 64, None, None, None, spec, 100, 100)
            fake_torch.profiler.profile.assert_not_called()
            self.assertEqual(study.call_args.args[-2:], (None, None))


class Storage:
    def __init__(self):
        self.ptr, self.size = 100, 64
    def data_ptr(self):
        return self.ptr
    def nbytes(self):
        return self.size


class Tensor:
    def __init__(self, storage):
        self.storage = storage
    def untyped_storage(self):
        return self.storage


class WeakStorage:
    def __init__(self, storage):
        self.ref, self.cdata = weakref.ref(storage), id(storage)
    def expired(self):
        return self.ref() is None


class CodecWeakRegistryTests(unittest.TestCase):
    def test_registry_keeps_only_weak_storage_and_primitive_metadata(self):
        storage = Storage()
        tensor = Tensor(storage)
        reference = weakref.ref(storage)
        registry = probe.LifetimeRegistry(WeakStorage)
        first = registry.add(tensor, "source", "pack0", "entry", True)
        self.assertEqual(registry.add(tensor, "payload", "pack0", "exit", True), first)
        self.assertEqual(len(registry.rows), 1)
        del tensor, storage
        gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(registry.handles[0].expired())
        self.assertEqual(registry.rows[0]["roles"], ["source", "payload"])

    def test_storage_resize_and_reference_overflow_rejected(self):
        storage, registry = Storage(), probe.LifetimeRegistry(WeakStorage)
        tensor = Tensor(storage)
        registry.add(tensor, "source", "pack0", "entry", True)
        storage.size += 1
        with self.assertRaises(probe.obs.ObserverError):
            registry.add(tensor, "payload", "pack0", "exit", True)
        with mock.patch.dict(probe.CONFIG, maximum_references=1):
            with self.assertRaises(probe.obs.ObserverError):
                registry.add(tensor, "payload", "pack0", "exit", True)

    def test_math_controls_reject_changed_input_and_gradient_without_quality_rescue(self):
        cases = []
        for spec in probe.CASES:
            cases.append({"spec": dict(spec), "operation": {"loss": 2.5, "gradient": {"sha256": "a" * 64}},
                          "stages": {"postload": {"model": {"initial_parameter_sha256": "b" * 64, "batch_sha256": "c" * 64}}}})
        self.assertTrue(all(all(row.values()) for row in probe.math_controls(cases).values()))
        cases[-1]["operation"]["gradient"]["sha256"] = "d" * 64
        cases[-1]["stages"]["postload"]["model"]["batch_sha256"] = "e" * 64
        controls = probe.math_controls(cases)["dense"]
        self.assertFalse(controls["gradient_bytes_identical"])
        self.assertFalse(controls["batch_bytes_identical"])


if __name__ == "__main__":
    unittest.main()
