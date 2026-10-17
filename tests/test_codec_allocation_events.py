"""Synthetic event fixtures only; never load Torch or execute a model."""
import unittest
from experiments.codec_allocation_events import reduce_events, boundary_summary


def event(ordinal, stamp, ptr, size, allocation_id=None):
    return dict(ordinal=ordinal, t_ns=stamp, ptr=ptr, bytes=size, total_allocated=0,
                start_tid=1, device="cpu", allocation_id=allocation_id)


class AllocationEventTests(unittest.TestCase):
    def marker(self, name="pack0", kind="pack", start=10, end=30):
        return dict(id=name, kind=kind, start_ns=start, end_ns=end, start_tid=1)

    def ref(self, name, ptr, size, at="exit", storage="s0"):
        return dict(observation_id=name, ptr=ptr, nbytes=size, at=at, marker_id="pack0", storage_id=storage)

    def test_pointer_reuse_is_two_allocations(self):
        rows = [event(0, 1, "p0", 40), event(1, 3, "p0", -40), event(2, 20, "p0", 40)]
        result = reduce_events(rows, [self.marker()], [self.ref("out", "p0", 40)])
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["allocations"]), 2)
        self.assertEqual(result["bindings"][0]["allocation"], "allocation-1")
        self.assertEqual(result["right_censored_allocation_ids"], ["allocation-1"])

    def test_returned_payload_excluded_from_temporary_live_max(self):
        rows = [event(0, 11, "temp", 100), event(1, 12, "payload", 25), event(2, 14, "temp", -100)]
        result = reduce_events(rows, [self.marker()], [self.ref("out", "payload", 25)])
        summary = result["callback_summaries"][0]
        self.assertEqual(summary["requested_bytes_created"], 125)
        self.assertEqual(summary["temporary_requested_live_max_bytes"], 100)
        self.assertEqual(summary["returned_allocation_ids"], ["allocation-1"])

    def test_source_aliases_deduplicated_at_owner_boundary(self):
        rows = [event(0, 1, "original", 4096)]
        refs = [self.ref("source", "original", 4096, "entry"),
                self.ref("dense_payload", "original", 4096)]
        reduced = reduce_events(rows, [self.marker()], refs)
        boundary = boundary_summary(reduced, self.marker("held", "boundary", 40, 42),
                                    [dict(storage_id="s0", expired=False)])
        self.assertEqual(boundary["bound_unique_live_requested_bytes"], 4096)
        self.assertEqual(boundary["disagreements"], 0)

    def test_unknown_baseline_free_retained_and_not_invented(self):
        result = reduce_events([event(0, 1, "old", -128)], [], [])
        self.assertEqual(len(result["unknown_preexisting_frees"]), 1)
        self.assertEqual(result["allocations"], [])

    def test_same_pointer_equal_time_is_not_rescued_by_ordinal(self):
        rows = [event(0, 11, "p", 40), event(1, 11, "p", -40)]
        result = reduce_events(rows, [self.marker()], [self.ref("out", "p", 40)])
        self.assertFalse(result["valid"])
        self.assertIsNone(result["bindings"][0]["allocation"])
        self.assertIsNone(result["callback_summaries"][0]["temporary_requested_live_max_bytes"])

    def test_size_or_optional_allocation_id_mismatch_rejects(self):
        for rows in ([event(0, 11, "p", 40), event(1, 12, "p", -41)],
                     [event(0, 11, "p", 40, 1), event(1, 12, "p", -40, 2)]):
            with self.subTest(rows=rows):
                self.assertFalse(reduce_events(rows, [self.marker()], [])["valid"])

    def test_weak_owner_disagreement_and_changed_probe_are_distinct(self):
        rows = [event(0, 1, "p", 100), event(1, 41, "p", -100)]
        reduced = reduce_events(rows, [self.marker()], [self.ref("x", "p", 100)])
        boundary = boundary_summary(reduced, self.marker("b", "boundary", 40, 42),
                                    [dict(storage_id="s0", expired=True)])
        self.assertEqual(boundary["unknown_owners"], 1)
        after = boundary_summary(reduced, self.marker("after", "boundary", 50, 52),
                                 [dict(storage_id="s0", expired=False)])
        self.assertEqual(after["disagreements"], 1)

    def test_empty_trace_not_success_and_missing_binding_explicit(self):
        result = reduce_events([], [self.marker()], [self.ref("missing", "p", 4)])
        self.assertFalse(result["valid"])
        self.assertEqual(result["bindings"][0]["status"], "unknown")

    def test_boundary_endpoint_ties_are_unknown(self):
        for stamp in (40, 42):
            rows = [event(0, 1, "p", 100), event(1, stamp, "p", -100)]
            reduced = reduce_events(rows, [self.marker()], [self.ref("x", "p", 100)])
            boundary = boundary_summary(reduced, self.marker("b", "boundary", 40, 42),
                                        [dict(storage_id="s0", expired=True)])
            self.assertEqual(boundary["unknown_owners"], 1)
            self.assertIsNone(boundary["bound_unique_live_requested_bytes"])
            self.assertFalse(boundary["selected_bound_subset_complete"])

    def test_unknown_baseline_free_inside_callback_cannot_mean_zero_workspace(self):
        result = reduce_events([event(0, 15, "missing_create", -128)], [self.marker()], [])
        self.assertTrue(result["valid"])
        callback = result["callback_summaries"][0]
        self.assertFalse(callback["valid"])
        self.assertIsNone(callback["temporary_requested_live_max_bytes"])
        self.assertIn("unknown_baseline_free_in_callback", callback["unknown_reasons"])

    def test_foreign_thread_allocation_is_not_callback_attribution(self):
        row = dict(event(0, 15, "foreign", 128), start_tid=2)
        callback = reduce_events([row], [self.marker()], [])["callback_summaries"][0]
        self.assertFalse(callback["valid"])
        self.assertEqual(callback["requested_bytes_created"], 0)
        self.assertIsNone(callback["temporary_requested_live_max_bytes"])

    def test_equal_time_mixed_sign_different_pointers_has_no_exact_peak(self):
        rows = [event(0, 11, "a", 10), event(1, 12, "a", -10),
                event(2, 12, "b", 50), event(3, 13, "b", -50)]
        result = reduce_events(rows, [self.marker()], [])
        self.assertTrue(result["valid"])
        callback = result["callback_summaries"][0]
        self.assertFalse(callback["valid"])
        self.assertIsNone(callback["temporary_requested_live_max_bytes"])
        self.assertIn("mixed_sign_equal_timestamp_peak_unknown", callback["unknown_reasons"])

    def test_duplicate_observations_reject_and_do_not_overwrite_binding(self):
        refs = [self.ref("same", "a", 10), self.ref("same", "b", 10)]
        result = reduce_events([event(0, 1, "a", 10), event(1, 2, "b", 10)], [self.marker()], refs)
        self.assertFalse(result["valid"])
        self.assertTrue(all(row["allocation"] is None for row in result["bindings"]))

    def test_invalid_marker_and_reference_position_fail_closed(self):
        variants = [([], [dict(self.ref("x", "p", 10), marker_id="missing")]),
                    ([self.marker()], [self.ref("x", "p", 10, at="invalid")]),
                    ([dict(self.marker(), end_ns=1)], [self.ref("x", "p", 10)])]
        for markers, refs in variants:
            with self.subTest(markers=markers, refs=refs):
                reduced = reduce_events([event(0, 1, "p", 10)], markers, refs)
                self.assertFalse(reduced["valid"])
                self.assertIsNone(reduced["bindings"][0]["allocation"])

    def test_malformed_event_is_data_failure_before_sorting(self):
        for bad in ({}, None, dict(event(0, 1, "p", 10), t_ns="1")):
            with self.subTest(bad=bad):
                self.assertFalse(reduce_events([bad], [], [])["valid"])

    def test_unknown_owner_keeps_selected_subtotal_labeled_partial(self):
        reduced = reduce_events([event(0, 1, "p", 100)], [self.marker()], [self.ref("x", "p", 100)])
        boundary = boundary_summary(reduced, self.marker("b", "boundary", 40, 42),
            [dict(storage_id="s0", expired=False), dict(storage_id="unbound", expired=False)])
        self.assertEqual(boundary["selected_bound_subset_requested_bytes"], 100)
        self.assertIsNone(boundary["bound_unique_live_requested_bytes"])
        self.assertEqual(boundary["known_owner_rows"], 1)
        self.assertEqual(boundary["total_owner_rows"], 2)


if __name__ == "__main__":
    unittest.main()
