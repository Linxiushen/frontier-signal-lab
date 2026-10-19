"""Bounded cooperative unit controls, separate from the frozen probe suite."""
import io
import json
from pathlib import Path
import sys
import threading
import unittest

if (Path(__file__).resolve().parent / "trace_ledger.py").is_file():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import trace_ledger as ledger_module
    import trace_ledger_probe as probe
else:
    from experiments import trace_ledger as ledger_module
    from experiments import trace_ledger_probe as probe


_controls_active = False


def _deny_runtime(event, args):
    if _controls_active and (event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "ctypes.dlopen"} or event.startswith("socket.")):
        raise RuntimeError("Unit controls denied capability: " + event)


def _deny_probe(*args, **kwargs):
    raise RuntimeError("Unit tests must not run the preregistered experiment")


sys.addaudithook(_deny_runtime)


def encoded(seq=0, kind="unit", **fields):
    return (json.dumps({"seq": seq, "kind": kind, **fields}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class CountingSink:
    def __init__(self):
        self.bytes = io.BytesIO()
        self.write_calls = self.flush_calls = 0

    def write(self, data):
        self.write_calls += 1
        return self.bytes.write(data)

    def flush(self):
        self.flush_calls += 1


class GatedSink(CountingSink):
    """Only the first call waits, with a finite cooperative fixture timeout."""
    def __init__(self):
        super().__init__()
        self.first_entered, self.release = threading.Event(), threading.Event()

    def write(self, data):
        self.write_calls += 1
        if self.write_calls == 1:
            self.first_entered.set()
            if not self.release.wait(2):
                raise TimeoutError("Unit fixture gate was not released")
        return self.bytes.write(data)


class TraceLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _controls_active
        cls._original_probe = (probe.run, probe.concurrent_arm, probe.fault_arm)
        probe.run = probe.concurrent_arm = probe.fault_arm = _deny_probe
        _controls_active = True

    @classmethod
    def tearDownClass(cls):
        global _controls_active
        _controls_active = False
        probe.run, probe.concurrent_arm, probe.fault_arm = cls._original_probe

    def launch(self, callback):
        failures = []
        def bounded():
            try:
                callback()
            except BaseException as exc:
                failures.append(exc)
        thread = threading.Thread(target=bounded, daemon=True)
        thread.start()
        return thread, failures

    def stopped(self, *launched):
        for thread, failures in launched:
            thread.join(2)
            self.assertFalse(thread.is_alive(), "Cooperative unit thread failed to stop")
            self.assertEqual(failures, [])

    def test_old_unlocked_algorithm_has_deterministic_duplicate_and_gap(self):
        # A minimal original stand-in reproduces the mechanism only. It does
        # not import or execute any prior native controller or repair evidence.
        sink, records = GatedSink(), []
        def old_append(item):
            row = {"kind": "old", "seq": len(records), "item": item}
            sink.write((json.dumps(row) + "\n").encode())
            sink.flush()
            records.append(row)
        first = self.launch(lambda: old_append("first"))
        second = None
        try:
            self.assertTrue(sink.first_entered.wait(1))
            second = self.launch(lambda: old_append("second"))
            self.stopped(second)
        finally:
            sink.release.set()
            self.stopped(first)
        old_append("third")
        self.assertEqual([json.loads(line)["seq"] for line in sink.bytes.getvalue().splitlines()], [0, 0, 2])
        self.assertEqual([row["seq"] for row in records], [0, 0, 2])

    def test_serialization_covers_assignment_write_flush_and_commit(self):
        sink = GatedSink()
        ledger = ledger_module.BoundedJSONLLedger(sink)
        second_started = threading.Event()
        first = self.launch(lambda: ledger.append("new", item="first"))
        second = None
        try:
            self.assertTrue(sink.first_entered.wait(1))
            def append_second():
                second_started.set()
                ledger.append("new", item="second")
            second = self.launch(append_second)
            self.assertTrue(second_started.wait(1))
            self.assertEqual(sink.write_calls, 1)
        finally:
            sink.release.set()
            self.stopped(first, *([] if second is None else [second]))
        raw = sink.bytes.getvalue()
        self.assertEqual(raw, encoded(0, "new", item="first") + encoded(1, "new", item="second"))
        self.assertEqual(ledger.snapshot()["committed_bytes"], len(raw))
        self.assertEqual((sink.write_calls, sink.flush_calls), (2, 2))

    def test_row_and_total_byte_caps_are_atomic_between_threads(self):
        for limits in [{"max_rows": 1}, {"max_total_bytes": len(encoded(item="same"))}]:
            with self.subTest(limits=limits):
                sink, barrier, outcomes = CountingSink(), threading.Barrier(2), []
                ledger = ledger_module.BoundedJSONLLedger(sink, **limits)
                def append():
                    barrier.wait(1)
                    try:
                        ledger.append("unit", item="same")
                        outcomes.append("committed")
                    except ledger_module.LedgerLimitError:
                        outcomes.append("refused")
                self.stopped(self.launch(append), self.launch(append))
                self.assertEqual(sorted(outcomes), ["committed", "refused"])
                self.assertEqual(sink.bytes.getvalue(), encoded(item="same"))
                self.assertEqual((sink.write_calls, sink.flush_calls), (1, 1))

    def test_unicode_exact_caps_count_utf8_and_refuse_before_io(self):
        row = encoded(kind="u", item="雪")
        sink = CountingSink()
        ledger = ledger_module.BoundedJSONLLedger(sink, max_rows=3,
            max_row_bytes=len(row), max_total_bytes=2 * len(row))
        ledger.append("u", item="雪")
        ledger.append("u", item="雪")
        with self.assertRaises(ledger_module.LedgerLimitError):
            ledger.append("u", item="雪")
        self.assertEqual(sink.bytes.getvalue(), row + encoded(1, "u", item="雪"))
        self.assertEqual(ledger.snapshot()["committed_bytes"], 2 * len(row))
        self.assertEqual((sink.write_calls, sink.flush_calls), (2, 2))
        small = CountingSink()
        short = ledger_module.BoundedJSONLLedger(small, max_row_bytes=len(row) - 1)
        with self.assertRaises(ledger_module.LedgerLimitError):
            short.append("u", item="雪")
        short.append("a")
        self.assertEqual(small.write_calls, 1)
        self.assertFalse(short.snapshot()["poisoned"])

    def test_pre_io_invalid_values_leave_prefix_usable(self):
        sink = CountingSink()
        ledger = ledger_module.BoundedJSONLLedger(sink)
        invalid = [lambda: ledger.append(""), lambda: ledger.append(1),
            lambda: ledger.append("unit", seq=4), lambda: ledger.append("unit", value=float("nan")),
            lambda: ledger.append("unit", value=object())]
        for call in invalid:
            with self.assertRaises((ValueError, TypeError)):
                call()
        self.assertEqual((sink.write_calls, sink.flush_calls), (0, 0))
        self.assertEqual(ledger.append("valid")["seq"], 0)
        self.assertFalse(ledger.snapshot()["poisoned"])

    def test_uncertain_io_poison_preserves_prefix_and_never_retries(self):
        for mode in ["short", "bool", "none", "write", "flush"]:
            with self.subTest(mode=mode):
                class Fault(CountingSink):
                    def write(self, data):
                        self.write_calls += 1
                        if self.write_calls == 1:
                            return self.bytes.write(data)
                        if mode == "write":
                            self.bytes.write(data[:5])
                            raise OSError("partial")
                        if mode == "short":
                            return self.bytes.write(data[:-1])
                        count = self.bytes.write(data)
                        return True if mode == "bool" else None if mode == "none" else count
                    def flush(self):
                        self.flush_calls += 1
                        if mode == "flush" and self.flush_calls == 2:
                            raise OSError("uncertain flush")
                sink = Fault()
                ledger = ledger_module.BoundedJSONLLedger(sink)
                ledger.append("prefix")
                prefix = ledger.snapshot()
                with self.assertRaises(ledger_module.LedgerIOError):
                    ledger.append("fault")
                state = ledger.snapshot()
                self.assertEqual(state["records"], prefix["records"])
                self.assertEqual(state["committed_bytes"], prefix["committed_bytes"])
                self.assertTrue(state["poisoned"])
                self.assertEqual(state["failure"]["seq"], 1)
                self.assertTrue(state["failure"]["sink_may_have_uncommitted_bytes"])
                self.assertFalse(state["failure"]["flush_completed"])
                self.assertEqual(state["failure"]["stage"], "flush" if mode == "flush" else "write")
                self.assertGreater(len(sink.bytes.getvalue()), state["committed_bytes"])
                before = (sink.bytes.getvalue(), sink.write_calls, sink.flush_calls)
                with self.assertRaises(ledger_module.LedgerPoisonedError):
                    ledger.append("no-retry")
                self.assertEqual(before, (sink.bytes.getvalue(), sink.write_calls, sink.flush_calls))
                state["failure"]["seq"] = 99
                self.assertEqual(ledger.snapshot()["failure"]["seq"], 1)

    def test_recursive_append_and_snapshot_fail_without_deadlock(self):
        for method in ["append", "snapshot"]:
            with self.subTest(method=method):
                sink = CountingSink()
                ledger = ledger_module.BoundedJSONLLedger(sink)
                def callback(data):
                    ledger.append("inner") if method == "append" else ledger.snapshot()
                sink.write = callback
                failures = []
                def outer():
                    try:
                        ledger.append("outer")
                    except ledger_module.LedgerIOError as exc:
                        failures.append(exc.__cause__)
                self.stopped(self.launch(outer))
                self.assertEqual(len(failures), 1)
                self.assertIsInstance(failures[0], ledger_module.LedgerReentrantError)
                self.assertTrue(ledger.snapshot()["poisoned"])
                self.assertEqual(ledger.snapshot()["committed_rows"], 0)

    def test_retained_records_do_not_alias_inputs_returns_or_snapshots(self):
        ledger = ledger_module.BoundedJSONLLedger(io.BytesIO())
        nested = {"values": [1, {"value": "original"}]}
        returned = ledger.append("nested", nested=nested)
        nested["values"][1]["value"] = "input mutation"
        returned["nested"]["values"].append(2)
        snap = ledger.snapshot()
        snap["records"][0]["nested"]["values"][1]["value"] = "snapshot mutation"
        self.assertEqual(ledger.snapshot()["records"][0]["nested"], {"values": [1, {"value": "original"}]})

    def test_invalid_constructor_caps(self):
        for name in ["max_rows", "max_row_bytes", "max_total_bytes"]:
            for value in [0, -1, True, None, 1.5]:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    ledger_module.BoundedJSONLLedger(io.BytesIO(), **{name: value})

    def test_saved_reader_rejects_sequence_json_schema_and_custody_mutations(self):
        self.assertEqual(probe.strict_json(b'{"finite":1.25}'), {"finite": 1.25})
        for raw_number in [b'{"number":1e999}', b'{"number":-1e999}', b'{"number":NaN}']:
            with self.assertRaises(ValueError):
                probe.strict_json(raw_number)
        row = encoded(item="00000000")
        options = dict(max_rows=2, max_row_bytes=512, max_total_bytes=1024,
            expected_ids=["00000000"], expected_kind="unit")
        self.assertEqual(probe.decode_trace(row, **options)[0]["item"], "00000000")
        mutations = [row + row, row.replace(b'"seq":0', b'"seq":1'), row[:-1], b"x" * 1025,
            b'{"kind":"unit","seq":0,"seq":0}\n', b'{"kind":"unit","seq":0,"x":NaN}\n',
            b'{"kind":"unit","seq":0,"x":1e999}\n',
            row.replace(b'"seq":0', b'"seq":true'), row.replace(b'"unit"', b'"wrong"'),
            row.replace(b'"00000000"', b'"invented"'), row.replace(b'"seq":0', b'"extra":1,"seq":0'),
            row.replace(b'"00000000"', b'"\xff"'), row.replace(b'"item":"00000000",', b'')]
        for raw in mutations:
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                probe.decode_trace(raw, **options)
        with self.assertRaises(RuntimeError):
            probe.run(None, None, None)


if __name__ == "__main__":
    unittest.main()
