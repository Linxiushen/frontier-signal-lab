"""Actual vf-run exhaustion study; deterministic loopback provider, no model.

The optional failure ledger preserves failed native artifacts without assigning
a selectable zero reward. Previous successful/failed suites remain unchanged.
"""
import argparse
import asyncio
import importlib
import inspect
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from experiments.eval_budget_outcomes import OutcomeBudgetLedger
from experiments.eval_budget_runner import canonical, digest, verify_files
from experiments.eval_http_budget import HttpBudget
from experiments.verifiers_budget_suite_v2 import FixtureHandler, load, resolve_request, save

if not __debug__:
    raise RuntimeError("acceptance assertions must remain enabled")


def config(output, protocol, key, model, stage, endpoint):
    """Original native runner config shape, with fixed native retry ceilings."""
    return {
        "env": {"taskset": {"id": "echo", "phrases": load(Path(protocol["datasets"][stage]["path"]))},
                "retries": {"max_retries": 0}, "timeout": {"episode": 35, "finalize": 5},
                "agent": {"harness": {"id": "null"}, "runtime": {"type": "subprocess"},
                          "max_turns": 1, "max_turn_tokens": 16, "max_input_tokens": 2048,
                          "max_output_tokens": 16, "max_total_tokens": 2064, "network_notice": False,
                          "timeout": {"setup": 15, "rollout": 10, "finalize": 5, "scoring": 5},
                          "retries": {"max_retries": 0}}},
        "model": model, "client": {"type": "eval", "base_url": endpoint,
            "api_key_var": "FRONTIER_LOCAL_FIXTURE_KEY",
            "headers": {"X-Frontier-Attempt": key, "X-Frontier-Data-SHA256": protocol["datasets"][stage]["sha256"]},
            "timeout": {"connect": 2, "read": 3, "write": 3, "pool": 2}},
        "sampling": {"max_tokens": 16, "temperature": 0}, "select": {"limit": 1},
        "num_rollouts": 1, "max_concurrent": 1, "output_dir": str(output / "native"),
        "run": {"name": key, "dir": key}}


def worker(protocol_path, output, phase, endpoint):
    protocol = load(protocol_path)
    verify_files(protocol["versions"])
    echo = importlib.import_module("echo")
    assert Path(echo.__file__).resolve() == Path(protocol["evaluator_path"]).resolve()
    ledger = OutcomeBudgetLedger(output / "budget.sqlite", digest(protocol_path.read_bytes()), 3)
    assert ledger.recover() == 0  # Both killed owners committed a terminal receipt first.
    save(output / f"worker-{phase}-start.json", {"pid": os.getpid(), "before": ledger.snapshot()})

    async def evaluate(key, model, stage, expected_ok):
        verify_files(protocol["versions"])
        if stage == "final":
            assert ledger.winner() == model
            save(output / "final-data-access.json", {"winner": model, "ledger": ledger.snapshot(), "before_read": True})
        data = Path(protocol["datasets"][stage]["path"]).read_bytes()
        assert digest(data) == protocol["datasets"][stage]["sha256"]
        from verifiers.v1.cli.run import run_episodes
        from verifiers.v1.configs.cli.run import RunnerConfig
        assert Path(inspect.getfile(run_episodes)).resolve() == Path('/source/verifiers/v1/cli/run.py')
        assert ledger.reserve(key, stage, model, digest(data))
        native_config = RunnerConfig.model_validate(config(output, protocol, key, model, stage, endpoint))
        started = time.perf_counter()
        episodes = await run_episodes(native_config)
        elapsed = time.perf_counter() - started
        assert len(episodes) == 1
        episode = episodes[0]
        raw = episode.to_json()
        with (output / f"{key}-episode.json").open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        # Preserve all upstream memberships, even rewards on a failed trace.
        evidence = {"episode_sha256": digest(raw), "runner_seconds": elapsed,
            "episode_ok": episode.ok, "episode_errors": len(episode.errors),
            "traces": [{"ok": trace.ok, "errors": len(trace.errors), "dropped": trace.is_dropped,
                        "num_turns": trace.num_turns, "rewards": {name: {"score": reward.score, "weight": reward.weight}
                        if reward is not None else None for name, reward in trace.rewards.items()}}
                       for trace in episode.traces]}
        assert episode.ok == expected_ok
        # Reject version drift before committing either terminal outcome.
        verify_files(protocol["versions"])
        if expected_ok:
            assert len(episode.traces) == 1
            trace = episode.traces[0]
            assert trace.ok and not trace.is_dropped and trace.num_turns == 1
            assert set(trace.rewards) == {"echoed"} and trace.reward == 0.0
            evidence.update(outcome="completed", accepted_score_denominator=1, reward=0.0)
            ledger.complete(key, 0.0, evidence)
        else:
            assert episode.errors or any(trace.errors for trace in episode.traces)
            evidence.update(outcome="native_failure", accepted_score_denominator=0, reward=None)
            ledger.fail(key, evidence)
        save(output / f"{key}-receipt.json", evidence)

    if phase == 1:
        asyncio.run(evaluate("dev-ok", "fixture-bad", "development", True))
    elif phase == 2:
        assert not ledger.reserve("dev-ok", "development", "fixture-bad", protocol["datasets"]["development"]["sha256"])
        asyncio.run(evaluate("dev-attempt-cap", "fixture-good", "development", False))
    elif phase == 3:
        assert not ledger.reserve("dev-attempt-cap", "development", "fixture-good", protocol["datasets"]["development"]["sha256"])
        original = ledger.snapshot()
        failed = original["attempts"][1]
        ledger.fail("dev-attempt-cap", json.loads(failed["receipt"]))
        assert original == ledger.snapshot()
        save(output / "failure-replay.json", {"before": original, "after": ledger.snapshot(), "native_entry_granted": False})
        asyncio.run(evaluate("dev-total-cap", "fixture-good", "development", False))
        assert ledger.seal_winner() == "fixture-bad"
        save(output / "selection.json", ledger.snapshot())
        asyncio.run(evaluate("final-once", "fixture-bad", "final", False))
        before = ledger.snapshot()
        assert not ledger.reserve("final-once", "final", "fixture-bad", protocol["datasets"]["final"]["sha256"])
        try:
            ledger.reserve("final-again", "final", "fixture-bad", protocol["datasets"]["final"]["sha256"])
        except ValueError:
            pass
        else:
            raise AssertionError("failed final allowance was refunded")
        assert before == ledger.snapshot()
        save(output / "worker-final.json", before)
        ledger.close()
        return
    else:
        raise ValueError("unknown phase")
    save(output / f"barrier-{phase}.json", {"pid": os.getpid(), "terminal_ledger": ledger.snapshot()})
    ledger.close()
    while True:
        time.sleep(0.1)


class ExhaustionServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, output, protocol, dialect, records):
        super().__init__(("127.0.0.1", 0), ExhaustionHandler)
        self.output, self.protocol, self.dialect, self.records = output, protocol, dialect, records
        self.guard = threading.Lock()
        self.budget = HttpBudget(output / "http-budget.sqlite", digest(canonical(protocol).encode()), 3, 1)


class ExhaustionHandler(FixtureHandler):
    def do_POST(self):
        # Fixed valid complete-body boundary only; malformed framing is not charged here.
        self.connection.settimeout(3)
        n = int(self.headers.get("Content-Length", "0"))
        request = self.rfile.read(min(max(n, 0), 16385))
        attempt = self.headers.get("X-Frontier-Attempt", "")
        with self.server.guard:
            slot = self.server.budget.receive(attempt, digest(request))
            index = slot["seq"]
            arrival = {"index": index, "received_monotonic": time.monotonic(), "attempt": attempt,
                "path": self.path, "data_hash": self.headers.get("X-Frontier-Data-SHA256", ""),
                "request_bytes": len(request), "request_sha256": digest(request),
                "request_body_complete": len(request) == n, "slot": slot, "status": "received"}
            self.server.records.append(arrival)
        (self.server.output / f"http-{index}-request.bin").write_bytes(request)
        try:
            if self.path != "/v1/chat/completions" or not 0 < n <= 16384 or len(request) != n:
                raise ValueError("request path/body refused")
            # Bind even refused requests to their logical reservation before preparing a response.
            body = json.loads(request)
            key, content = resolve_request(self.server.output / "budget.sqlite", self.server.protocol,
                                           attempt, arrival["data_hash"], body)
            arrival.update(key=key, stream=bool(body.get("stream")))
            if not slot["admitted"]:
                # 403 is terminal in the unmodified SDK; 409 would trigger more retries.
                status, response, content_type = 403, canonical({"error": {"message": slot["reason"]}}).encode(), "application/json"
            elif attempt == "dev-attempt-cap":
                status, response, content_type = 503, canonical({"error": {"message": "fixed transient failure"}}).encode(), "application/json"
            else:
                assert attempt == "dev-ok"
                raw = {"id": "chatcmpl-local-fixture", "object": "chat.completion", "created": 0,
                    "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                response = b"".join(self.server.dialect.stream_events(raw)) if body.get("stream") else canonical(raw).encode()
                status, content_type = 200, "text/event-stream" if body.get("stream") else "application/json"
            self.server.budget.response(index, status, False)
            self.deliver(index, arrival, status, response, content_type)
            self.server.budget.response(index, status, True)
        except Exception as error:
            arrival.update(status="handler_failed", error=repr(error))
            if "response_bytes" not in arrival:
                try:
                    self.server.budget.response(index, 400, False)
                    self.deliver(index, arrival, 400, canonical({"error": {"message": "fixture handler failed"}}).encode(), "application/json")
                    self.server.budget.response(index, 400, True)
                except Exception as write_error:
                    arrival["write_error"] = repr(write_error)
            arrival["status"] = "handler_failed"
        finally:
            arrival["finished_monotonic"] = time.monotonic()
            save(self.server.output / f"http-{index}-arrival.json", arrival)


def controller(protocol_path, output):
    protocol = load(protocol_path)
    verify_files(protocol["versions"])
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    from verifiers.v1.dialects.chat import ChatDialect
    dialect = ChatDialect()
    initialization_seconds = time.perf_counter() - started
    processes, records, samples, listeners = [], [], [], []
    current = server = thread = stdout = stderr = None
    observer_seconds = 0.0
    try:
        for phase, before_count, after_count in [(1, 0, 1), (2, 1, 3), (3, 3, 5)]:
            server = ExhaustionServer(output, protocol, dialect, records)
            assert len(server.budget.snapshot()["arrivals"]) == before_count
            listeners.append({"phase": phase, "before": server.budget.snapshot(), "port": server.server_port})
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stdout = (output / f"worker-{phase}-stdout.log").open("xb")
            stderr = (output / f"worker-{phase}-stderr.log").open("xb")
            current = subprocess.Popen([sys.executable, __file__, "worker", str(protocol_path), str(output), str(phase), f"http://127.0.0.1:{server.server_port}/v1"],
                stdout=stdout, stderr=stderr, start_new_session=True)
            deadline = time.monotonic() + 55
            barrier = output / f"barrier-{phase}.json"
            while True:
                rc = current.poll()
                if rc is not None:
                    if phase == 3 and rc == 0:
                        break
                    raise RuntimeError(f"worker {phase} exited {rc}")
                if phase < 3 and barrier.exists():
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"worker {phase} deadline")
                t = time.perf_counter()
                samples.append({"monotonic": time.monotonic(), **{name: int(Path('/sys/fs/cgroup/' + file).read_text())
                    for name, file in [("memory_current", "memory.current"), ("pids_current", "pids.current")]}})
                observer_seconds += time.perf_counter() - t
                time.sleep(0.1)
            if phase < 3:
                assert current.poll() is None
                os.killpg(current.pid, signal.SIGKILL)
            rc = current.wait(timeout=5)
            processes.append({"phase": phase, "pid": current.pid, "returncode": rc, "forced_kill": phase < 3})
            assert rc == (-signal.SIGKILL if phase < 3 else 0)
            stdout.close(); stderr.close(); stdout = stderr = None; current = None
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            assert not thread.is_alive()
            snapshot = server.budget.snapshot()
            assert len(snapshot["arrivals"]) == after_count
            save(output / f"http-budget-phase-{phase}.json", snapshot)
            server = thread = None
        final = load(output / "worker-final.json")
        assert [row["status"] for row in final["attempts"]] == ["completed", "failed", "failed", "failed"]
        assert [row["reward"] for row in final["attempts"]] == [0.0, None, None, None]
        assert final["metadata"]["winner"] == "fixture-bad"
        assert [row["response_status"] for row in records] == [200, 503, 403, 403, 403]
        assert [row["slot"]["reason"] for row in records] == ["admitted", "admitted", "attempt_exhausted", "total_exhausted", "total_exhausted"]
        assert [row["attempt"] for row in records] == ["dev-ok", "dev-attempt-cap", "dev-attempt-cap", "dev-total-cap", "final-once"]
        assert all(row["status"] == "delivered" and row["write_completed"] and row["request_body_complete"] for row in records)
        assert records[1]["request_sha256"] == records[2]["request_sha256"]
        assert len({row["pid"] for row in processes}) == 3
        result = {"status": "passed", "native_entries": 4, "completed_entries": 1, "failed_entries": 3,
            "accepted_score_members": 1, "final_score_members": 0, "provider_requests": 5, "admitted_requests": 2,
            "forced_kills": 2, "processes": processes, "suite_seconds": time.perf_counter() - started}
    except BaseException as error:
        if current is not None and current.poll() is None:
            os.killpg(current.pid, signal.SIGKILL); current.wait(timeout=5)
        result = {"status": "failed", "error": repr(error), "processes": processes, "provider_requests": len(records),
            "suite_seconds": time.perf_counter() - started, "no_retry": True}
    finally:
        if server is not None:
            server.shutdown(); server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        if current is not None:
            processes.append({"phase": phase, "pid": current.pid, "returncode": current.poll(), "failure_cleanup": True})
        for stream in (stdout, stderr):
            if stream is not None:
                stream.close()
        save(output / "http-receipts.json", records)
        save(output / "listener-restarts.json", listeners)
        save(output / "resource-samples.json", samples)
    result.update(fixture_initialization_seconds=initialization_seconds, observer_read_seconds=observer_seconds,
        memory_peak_cgroup_bytes=int(Path('/sys/fs/cgroup/memory.peak').read_text()),
        request_body_bytes=sum(row["request_bytes"] for row in records), response_body_bytes=sum(row.get("response_bytes", 0) for row in records),
        limitations=protocol["limitations"])
    save(output / "result.json", result)
    print(canonical(result))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["worker", "controller"])
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("phase", type=int, nargs="?")
    parser.add_argument("endpoint", nargs="?")
    args = parser.parse_args()
    if args.mode == "worker":
        worker(args.protocol, args.output, args.phase, args.endpoint)
    else:
        controller(args.protocol, args.output)
