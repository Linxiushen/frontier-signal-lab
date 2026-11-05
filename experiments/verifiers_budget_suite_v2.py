"""Separately versioned native vf-run integration with an explicit deterministic HTTP fixture.

The caller wraps the real run_episodes -> Env.run_slot -> NullHarness subprocess ->
EvalClient -> EchoTask.reward chain. It never patches Verifiers or replaces its
runner/scorer with a fake. The provider IS a fixture, and its token counts are
synthetic. This module establishes no real-model quality or production guarantee.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from experiments.eval_budget_runner import BudgetLedger, canonical, digest, verify_files

if not __debug__:
    raise RuntimeError("native acceptance requires Python assertions enabled")


def save(path: Path, value: object) -> None:
    data = (canonical(value) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def load(path: Path):
    return json.loads(path.read_bytes())


def expected_refusal(call):
    try:
        call()
    except ValueError:
        return True
    raise AssertionError("required refusal did not happen")


def worker(protocol_path: Path, output: Path, phase: int, endpoint: str) -> None:
    protocol = load(protocol_path)
    verify_files(protocol["versions"])
    # The upstream fixture is a plugin on PYTHONPATH, not a bundled taskset.
    echo = importlib.import_module("echo")
    if Path(echo.__file__).resolve() != Path(protocol["evaluator_path"]).resolve():
        raise ValueError("resolved echo plugin is not the frozen evaluator")
    ledger = BudgetLedger(output / "budget.sqlite", digest(protocol_path.read_bytes()), 3)
    burned = ledger.recover()
    save(output / f"worker-{phase}-start.json", {"pid": os.getpid(), "burned": burned})

    async def evaluate(key, model, data_path, stage):
        # The sealed data file is opened only after the winner has been committed.
        if stage == "final":
            assert ledger.winner() == model
        verify_files(protocol["versions"])
        data_bytes = data_path.read_bytes()
        assert digest(data_bytes) == protocol["datasets"][stage]["sha256"]
        from verifiers.v1.cli.run import run_episodes
        from verifiers.v1.configs.cli.run import RunnerConfig
        if Path(inspect.getfile(run_episodes)).resolve() != Path('/source/verifiers/v1/cli/run.py'):
            raise ValueError("resolved runner is not the frozen native source")
        assert ledger.reserve(key, stage, model, digest(data_bytes))

        cfg = RunnerConfig.model_validate({
            "env": {"taskset": {"id": "echo", "phrases": load(data_path)},
                    "retries": {"max_retries": 0},
                    "timeout": {"episode": 35, "finalize": 5},
                    "agent": {"harness": {"id": "null"},
                              "runtime": {"type": "subprocess"},
                              "max_turns": 1, "max_turn_tokens": 16,
                              "max_input_tokens": 2048, "max_output_tokens": 16,
                              "max_total_tokens": 2064, "network_notice": False,
                              "timeout": {"setup": 15, "rollout": 10, "finalize": 5, "scoring": 5},
                              "retries": {"max_retries": 0}}},
            "model": model, "client": {"type": "eval", "base_url": endpoint,
                "api_key_var": "FRONTIER_LOCAL_FIXTURE_KEY",
                "headers": {"X-Frontier-Attempt": key, "X-Frontier-Data-SHA256": digest(data_bytes)},
                "timeout": {"connect": 2, "read": 3, "write": 3, "pool": 2}},
            "sampling": {"max_tokens": 16, "temperature": 0},
            "select": {"limit": 1}, "num_rollouts": 1, "max_concurrent": 1,
            "output_dir": str(output / "native"), "run": {"name": key, "dir": key}})
        started = time.perf_counter()
        episodes = await run_episodes(cfg)
        elapsed = time.perf_counter() - started
        assert len(episodes) == 1 and episodes[0].ok
        assert len(episodes[0].traces) == 1
        trace = episodes[0].traces[0]
        assert trace.ok and not trace.is_dropped and trace.num_turns == 1
        assert set(trace.rewards) == {"echoed"} and trace.rewards["echoed"] is not None
        assert trace.rewards["echoed"].weight == 1.0
        reward = trace.reward
        assert reward == (0.0 if model == "fixture-bad" else 1.0)
        assert trace.rewards["echoed"].score == reward
        raw = episodes[0].to_json()
        with (output / f"{key}-episode.json").open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        receipt = {"episode_sha256": digest(raw), "denominator": 1,
                   "reward": reward, "runner_seconds": elapsed,
                   "num_turns": trace.num_turns, "score_members": list(trace.rewards)}
        verify_files(protocol["versions"])
        ledger.complete(key, reward, receipt)
        save(output / f"{key}-receipt.json", receipt)

    if phase == 1:
        asyncio.run(evaluate("dev-bad", "fixture-bad", Path(protocol["datasets"]["development"]["path"]), "development"))
        save(output / "barrier-1.json", {"boundary": "completed score and ledger committed; before owner acknowledgement"})
    elif phase == 2:
        before = ledger.snapshot()
        before_monotonic = time.monotonic()
        wrong = dict(protocol["versions"])
        oracle = protocol["evaluator_path"]
        wrong[oracle] = "0" * 64
        assert expected_refusal(lambda: verify_files(wrong))
        after = ledger.snapshot()
        after_monotonic = time.monotonic()
        assert before == after
        save(output / "version-before.json", before)
        save(output / "version-after.json", after)
        save(output / "version-refusal.json", {"refused": True, "ledger_unchanged": True, "native_calls": 0,
             "before_monotonic": before_monotonic, "after_monotonic": after_monotonic})
        assert not ledger.reserve("dev-bad", "development", "fixture-bad", protocol["datasets"]["development"]["sha256"])
        asyncio.run(evaluate("dev-good", "fixture-good", Path(protocol["datasets"]["development"]["path"]), "development"))
        assert ledger.reserve("dev-uncertain", "development", "fixture-unused", protocol["datasets"]["development"]["sha256"])
        save(output / "barrier-2.json", {"boundary": "episode and score allowance reserved; before native entry"})
    elif phase == 3:
        assert burned == 1
        assert not ledger.reserve("dev-uncertain", "development", "fixture-unused", protocol["datasets"]["development"]["sha256"])
        assert expected_refusal(lambda: ledger.reserve("dev-bad", "development", "changed-model", "changed-data"))
        assert expected_refusal(lambda: ledger.reserve("dev-extra", "development", "fixture-extra", "x"))
        assert ledger.seal_winner() == "fixture-good"
        save(output / "selection.json", {"winner": ledger.winner(), "selected_from": ["dev-bad", "dev-good"], "before_final_data_open": True})
        asyncio.run(evaluate("final-once", "fixture-good", Path(protocol["datasets"]["final"]["path"]), "final"))
        assert not ledger.reserve("final-once", "final", "fixture-good", protocol["datasets"]["final"]["sha256"])
        assert expected_refusal(lambda: ledger.reserve("final-again", "final", "fixture-good", protocol["datasets"]["final"]["sha256"]))
        assert expected_refusal(lambda: ledger.reserve("late-dev", "development", "fixture-extra", "x"))
        save(output / "worker-final.json", ledger.snapshot())
        ledger.close()
        return
    else:
        raise ValueError("unknown phase")
    ledger.close()
    # Explicit barrier waits; controller proves this PID stopped before the next owner.
    while True:
        time.sleep(0.1)


def resolve_request(database: Path, protocol: dict, attempt: str, data_hash: str, body: dict):
    """Bind an actual request to its durable reservation, without arrival ordering."""
    db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = db.execute("SELECT phase,status,model,data_hash FROM attempts WHERE key=?", (attempt,)).fetchone()
        winner = db.execute("SELECT value FROM metadata WHERE key='winner'").fetchone()
    finally:
        db.close()
    if row is None or row[1] != "reserved":
        raise ValueError("request needs an existing active reservation")
    phase, _, model, frozen_data = row
    if model != body.get("model") or data_hash != frozen_data or data_hash != protocol["datasets"][phase]["sha256"]:
        raise ValueError("request model or data conflicts with reservation")
    if phase == "final" and (winner is None or winner[0] != model):
        raise ValueError("final request requires committed winner")
    prompt = body["messages"][-1]["content"]
    prefix = ("Answer directly without using tools or running code. Your reply "
              "must contain this exact phrase: ")
    # Exact pinned EchoTask prompt, not an arbitrary suffix accepted as the dataset.
    if not isinstance(prompt, str) or not prompt.startswith(prefix):
        raise ValueError("request prompt is not the frozen EchoTask input")
    phrase = prompt[len(prefix):]
    if digest((canonical([phrase]) + "\n").encode()) != data_hash:
        raise ValueError("request phrase conflicts with reserved data")
    if model not in {"fixture-bad", "fixture-good"}:
        raise ValueError("unsupported fixture model")
    return attempt, "deliberate mismatch" if model == "fixture-bad" else phrase


class FixtureServer(ThreadingHTTPServer):
    # Join request threads before final receipts, rather than losing late mutations.
    daemon_threads = False

    def __init__(self, output, protocol, dialect):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.output, self.protocol, self.dialect = output, protocol, dialect
        self.records = []
        self.guard = threading.Lock()


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        with self.server.guard:
            index = len(self.server.records) + 1
            arrival = {"index": index, "received_monotonic": time.monotonic(), "status": "received", "path": self.path}
            self.server.records.append(arrival)
        try:
            self.connection.settimeout(3)
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0:
                raise ValueError("positive content length required")
            request = self.rfile.read(min(n, 16385))
            (self.server.output / f"http-{index}-request.bin").write_bytes(request)
            arrival.update(request_bytes=len(request), request_sha256=digest(request),
                           request_body_complete=len(request) == n,
                           attempt=self.headers.get("X-Frontier-Attempt", ""),
                           data_hash=self.headers.get("X-Frontier-Data-SHA256", ""))
            if self.path != "/v1/chat/completions" or not 0 < n <= 16384 or len(request) != n:
                raise ValueError("request path/body limit or length refused")
            if index > self.server.protocol["specification"]["workload"]["http_arrival_ceiling"]:
                raise ValueError("HTTP arrival budget exhausted")
            body = json.loads(request)
            key, content = resolve_request(self.server.output / "budget.sqlite", self.server.protocol,
                                           arrival["attempt"], arrival["data_hash"], body)
            raw = {"id": "chatcmpl-local-fixture", "object": "chat.completion", "created": 0,
                   "model": body["model"], "choices": [{"index": 0,
                   "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            response = b"".join(self.server.dialect.stream_events(raw)) if body.get("stream") else canonical(raw).encode()
            arrival.update(key=key, stream=bool(body.get("stream")), status="prepared")
            self.deliver(index, arrival, 200, response, "text/event-stream" if body.get("stream") else "application/json")
        except Exception as error:
            arrival.update(status="refused_or_failed", error=repr(error))
            if "response_bytes" not in arrival:
                response = canonical({"error": {"message": "local fixture rejected request"}}).encode()
                try:
                    self.deliver(index, arrival, 409, response, "application/json")
                except Exception as write_error:
                    arrival["error_response_write_error"] = repr(write_error)
                arrival["status"] = "refused_or_failed"
        finally:
            arrival["finished_monotonic"] = time.monotonic()
            save(self.server.output / f"http-{index}-arrival.json", arrival)

    def deliver(self, index, arrival, status, response, content_type):
        (self.server.output / f"http-{index}-response.bin").write_bytes(response)
        arrival.update(response_bytes=len(response), response_sha256=digest(response), response_status=status,
                       response_prepared_monotonic=time.monotonic(), write_completed=False)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)
        self.wfile.flush()
        arrival.update(status="delivered", write_completed=True, write_completed_monotonic=time.monotonic())


def controller(protocol_path: Path, output: Path) -> None:
    protocol = load(protocol_path)
    verify_files(protocol["versions"])
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    # Initialize genuine formatter before serving. Its cold cost remains in suite time.
    initialization_start = time.perf_counter()
    from verifiers.v1.dialects.chat import ChatDialect
    dialect = ChatDialect()
    initialization_seconds = time.perf_counter() - initialization_start
    save(output / "fixture-initialization.json", {"seconds": initialization_seconds, "before_listen": True})
    server = FixtureServer(output, protocol, dialect)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    processes = []
    samples = []
    observer_seconds = 0.0
    current = None
    try:
        for phase in (1, 2, 3):
            stdout = (output / f"worker-{phase}-stdout.log").open("xb")
            stderr = (output / f"worker-{phase}-stderr.log").open("xb")
            current = subprocess.Popen([sys.executable, __file__, "worker", str(protocol_path), str(output), str(phase), endpoint], stdout=stdout, stderr=stderr, start_new_session=True)
            deadline = time.monotonic() + 55
            barrier = output / f"barrier-{phase}.json"
            while (not barrier.exists() if phase < 3 else current.poll() is None):
                if current.poll() is not None:
                    if phase < 3 or current.returncode != 0:
                        raise RuntimeError(f"worker {phase} exited {current.returncode}")
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"worker {phase} deadline")
                t = time.perf_counter()
                samples.append({"monotonic": time.monotonic(), **{name: int(Path('/sys/fs/cgroup/' + filename).read_text()) for name, filename in [("memory_current", "memory.current"), ("pids_current", "pids.current")]}})
                observer_seconds += time.perf_counter() - t
                time.sleep(0.1)
            if phase < 3:
                assert current.poll() is None
                os.killpg(current.pid, signal.SIGKILL)
            rc = current.wait(timeout=5)
            processes.append({"phase": phase, "pid": current.pid, "returncode": rc, "forced_kill": phase < 3})
            assert rc == (-signal.SIGKILL if phase < 3 else 0)
            stdout.close(); stderr.close(); current = None
        final = load(output / "worker-final.json")
        assert len({p["pid"] for p in processes}) == 3
        rows = final["attempts"]
        assert len(rows) == 4
        assert [r["status"] for r in rows] == ["completed", "completed", "burned", "completed"]
        assert [r["reward"] for r in rows] == [0.0, 1.0, None, 1.0]
        assert len(server.records) == 3 and all(r["status"] == "delivered" for r in server.records)
        assert final["metadata"]["winner"] == "fixture-good"
        assert load(output / "worker-2-start.json")["burned"] == 0
        assert load(output / "worker-3-start.json")["burned"] == 1
        result = {"status": "passed", "finite_scope": "actual vf-run/NullHarness/EvalClient/Echo reward with deterministic loopback fixture and one trusted owner", "development_reservations": 3,
            "completed_development": 2, "burned_development": 1, "final_reservations": 1,
            "native_episodes": 3, "native_scores": 3, "provider_requests": 3,
            "forced_kills": 2, "processes": processes, "fixture_final_reward": 1.0,
            "suite_seconds": time.perf_counter() - started, "fixture_initialization_seconds": initialization_seconds, "observer_read_seconds": observer_seconds,
            "memory_peak_cgroup_bytes": int(Path('/sys/fs/cgroup/memory.peak').read_text()),
            "request_body_bytes": sum(r["request_bytes"] for r in server.records),
            "response_body_bytes": sum(r["response_bytes"] for r in server.records),
            "limitations": protocol["limitations"]}
    except BaseException as error:
        if current is not None and current.poll() is None:
            os.killpg(current.pid, signal.SIGKILL); current.wait(timeout=5)
        result = {"status": "failed", "error": repr(error), "processes": processes,
                  "provider_requests": len(server.records), "suite_seconds": time.perf_counter() - started,
                  "limitations": protocol["limitations"], "no_retry": True,
                  "fixture_initialization_seconds": initialization_seconds,
                  "observer_read_seconds": observer_seconds,
                  "memory_peak_cgroup_bytes": int(Path("/sys/fs/cgroup/memory.peak").read_text())}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        if current is not None:
            processes.append({"phase": phase, "pid": current.pid, "returncode": current.poll(), "failure_cleanup": True})
            stdout.close(); stderr.close()
        save(output / "http-receipts.json", server.records)
        save(output / "resource-samples.json", samples)
    save(output / "result.json", result)
    print(canonical(result))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["controller", "worker"])
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("phase", type=int, nargs="?")
    parser.add_argument("endpoint", nargs="?")
    args = parser.parse_args()
    if args.mode == "worker":
        worker(args.protocol, args.output, args.phase, args.endpoint)
    else:
        controller(args.protocol, args.output)
