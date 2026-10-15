"""Numerical tiling contract and a small real fresh-process memory observation."""
import copy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from experiments.attnres_budget_probe import full_mix, make_bank, make_query, quantize_vectors
from experiments import attnres_memory_probe as probe


class TiledMixTests(unittest.TestCase):
    def test_tiled_matches_quantized_full_for_odd_tiles_and_extreme_logits(self):
        bank = make_bank(13, 7, 17, 7, "random")
        bank[0, 0] = 0
        packed, scales = quantize_vectors(bank)
        original_query = np.array(make_query(bank, 7, "fixed_random"), dtype=np.float32)
        for strength in (0.0, 1.0, 10000.0):
            query = original_query * np.float32(strength)
            expected = full_mix(packed.astype(np.float32) * scales, query)
            for tile in (1, 4, 13, 100):
                with self.subTest(strength=strength, tile=tile):
                    actual = probe.int8_tiled_mix(packed, scales, query, tile)
                    np.testing.assert_allclose(actual, expected, rtol=probe.RTOL, atol=probe.ATOL)
                    self.assertEqual(actual.dtype, np.float32)
                    self.assertTrue(np.all(np.isfinite(actual)))

    def test_zero_vectors_and_single_depth_are_finite_and_exact(self):
        query = np.full((3, 5), 10000, dtype=np.float32)
        zeros = np.zeros((9, 3, 5), dtype=np.float32)
        packed, scales = quantize_vectors(zeros)
        np.testing.assert_array_equal(probe.int8_tiled_mix(packed, scales, query, 2), zeros[0])
        bank = make_bank(1, 3, 5, 8, "random")
        packed, scales = quantize_vectors(bank)
        np.testing.assert_array_equal(probe.int8_tiled_mix(packed, scales, query, 1), packed[0].astype(np.float32) * scales[0])

    def test_token_isolation(self):
        bank = make_bank(9, 4, 7, 7, "random")
        query = np.array(make_query(bank, 7, "fixed_random"), dtype=np.float32)
        packed, scales = quantize_vectors(bank)
        expected = probe.int8_tiled_mix(packed, scales, query, 3)
        changed = packed.copy()
        changed[:, 2] = 127
        actual = probe.int8_tiled_mix(changed, scales, query, 3)
        np.testing.assert_array_equal(actual[[0, 1, 3]], expected[[0, 1, 3]])

    def test_invalid_tiles_input_and_resource_configuration_fail(self):
        bank = make_bank(3, 2, 4, 7, "random")
        packed, scales = quantize_vectors(bank)
        query = np.array(make_query(bank, 7, "fixed_random"), dtype=np.float32)
        for tile in (0, -1, True, 1.5):
            with self.subTest(tile=tile), self.assertRaises(ValueError):
                probe.int8_tiled_mix(packed, scales, query, tile)
        with self.assertRaises(ValueError):
            probe.int8_tiled_mix(packed, scales * 0, query)
        for values in (([2], 2, 4, [7], 4, 1), ([2], 2, 4, [-1], 1, 1), ([2, 2], 2, 4, [7], 1, 1), ([2**20], 256, 256, [7], 1, 1)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                probe.validate_config(*values)


class MemoryWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="attnres-memory-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name)
        cls.report = probe.run_probe([7], 5, 11, [7], 1, 3, cls.output)

    def test_fresh_workers_load_only_needed_bank_and_measure_os_memory(self):
        workers = self.report["worker_measurements"]
        self.assertEqual(len(workers), 3)
        self.assertEqual(len({w["pid"] for w in workers}), 3)
        for worker in workers:
            raw_path = self.output / worker["worker_record_file"]
            self.assertNotIn(b"\r\n", raw_path.read_bytes())
            names = worker["loaded_arrays"]
            self.assertEqual(set(names), {"bank", "query"} if worker["method"] == "dense_float32" else {"packed", "scales", "query"})
            for phase in worker["memory"].values():
                self.assertGreater(phase["peak_bytes"], 0)
                self.assertIn("backend", phase)
            self.assertGreaterEqual(worker["process_peak_bytes"], worker["memory"]["post_import_before_input"]["peak_bytes"])
            self.assertGreaterEqual(worker["operator_wall_seconds"], 0)
            self.assertGreaterEqual(worker["load_and_input_hash_wall_seconds"], 0)
            # No assertions that one method must be faster or use less memory.

    def test_persisted_outputs_match_independent_references_and_hashes(self):
        bank = make_bank(7, 5, 11, 7, "random")
        query = np.array(make_query(bank, 7, "fixed_random"), dtype=np.float32)
        dense = full_mix(bank, query)
        packed, scales = quantize_vectors(bank)
        quantized = full_mix(packed.astype(np.float32) * scales, query)
        for worker in self.report["worker_measurements"]:
            output = self.output / worker["output_file"]
            actual = np.load(output, allow_pickle=False)
            expected = dense if worker["method"] == "dense_float32" else quantized
            np.testing.assert_allclose(actual, expected, rtol=probe.RTOL, atol=probe.ATOL)
            self.assertEqual(probe.file_hash(output), worker["output_file_sha256"])
            self.assertEqual(probe.array_hash(actual), worker["output_array_sha256"])
        self.assertTrue(self.report["all_numerical_checks_passed"])

    def test_stable_hash_excludes_variable_measurements_and_observation_hash_covers_them(self):
        report = copy.deepcopy(self.report)
        observation_hash = report.pop("observation_sha256")
        self.assertEqual(probe.digest(report), observation_hash)
        stable = report["stable_results"]
        self.assertEqual(probe.digest(stable), report["stable_result_sha256"])
        self.assertEqual(stable["config_sha256"], probe.digest(report["config"]))
        report["worker_measurements"][0]["operator_wall_seconds"] += 1
        self.assertEqual(probe.digest(report["stable_results"]), report["stable_result_sha256"])
        self.assertNotEqual(probe.digest(report), observation_hash)
        self.assertIn("not isolated operator peaks", probe.render_markdown(self.report))


class LinuxMemoryBackendTests(unittest.TestCase):
    def test_procfs_peak_takes_precedence_over_inherited_resource_high_water(self):
        resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=999999))
        status = "Name:\tpython\nVmHWM:\t20000 kB\nVmRSS:\t19000 kB\n"
        with mock.patch.object(probe.platform, "system", return_value="Linux"), mock.patch.dict(sys.modules, resource=resource), mock.patch.object(Path, "read_text", return_value=status):
            observed = probe.process_memory()
        self.assertEqual(observed["peak_bytes"], 20000 * 1024)
        self.assertEqual(observed["resident_bytes"], 19000 * 1024)
        self.assertEqual(observed["resource_ru_maxrss_bytes_diagnostic"], 999999 * 1024)
        self.assertEqual(observed["backend"], "/proc/self/status VmHWM/VmRSS")

    def test_procfs_unavailable_reports_resource_fallback_caveat(self):
        resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=12345))
        with mock.patch.object(probe.platform, "system", return_value="Linux"), mock.patch.dict(sys.modules, resource=resource), mock.patch.object(Path, "read_text", side_effect=OSError("unavailable")):
            observed = probe.process_memory()
        self.assertEqual(observed["peak_bytes"], 12345 * 1024)
        self.assertIsNone(observed["resident_bytes"])
        self.assertIn("inherited pre-exec", observed["backend"])


if __name__ == "__main__":
    unittest.main()
