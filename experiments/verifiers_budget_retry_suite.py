"""One native retry study, with durable physical admissions across listener restarts.

Uses the unmodified v2 native worker and genuine pinned runner/SDK/scorer. The
provider is a deterministic loopback fixture. No real model or production proof.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from experiments.eval_budget_runner import canonical, digest, verify_files
from experiments.eval_http_budget import HttpBudget
from experiments.verifiers_budget_suite_v2 import FixtureHandler, load, resolve_request, save, worker

if not __debug__:
    raise RuntimeError("native acceptance requires assertions enabled")


class RetryServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, output, protocol, dialect, records):
        super().__init__(("127.0.0.1", 0), RetryHandler)
        self.output, self.protocol, self.dialect, self.records = output, protocol, dialect, records
        self.guard = threading.Lock()
        self.budget = HttpBudget(output / "http-budget.sqlite", digest(canonical(protocol).encode()), 6, 2)


class RetryHandler(FixtureHandler):
    def do_POST(self):
        # Admission starts after framing/body read; failures before this boundary are outside
        # the fixture ledger. All fixed native calls must reach complete-body admission.
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
            if not slot["admitted"]:
                raise ValueError("physical budget refused: " + slot["reason"])
            body = json.loads(request)
            key, content = resolve_request(self.server.output / "budget.sqlite", self.server.protocol,
                                           attempt, arrival["data_hash"], body)
            arrival.update(key=key, stream=bool(body.get("stream")))
            if slot["attempt_ordinal"] == 1:
                response = canonical({"error": {"message": "preregistered transient fixture failure", "type": "server_error"}}).encode()
                arrival["injected_transient"] = True
                status, content_type = 503, "application/json"
            else:
                raw = {"id": "chatcmpl-local-fixture", "object": "chat.completion", "created": 0,
                       "model": body["model"], "choices": [{"index": 0,
                       "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                response = b"".join(self.server.dialect.stream_events(raw)) if body.get("stream") else canonical(raw).encode()
                status, content_type = 200, "text/event-stream" if body.get("stream") else "application/json"
            # Prepared status survives a write failure; the physical allowance is never refunded.
            self.server.budget.response(index, status, False)
            self.deliver(index, arrival, status, response, content_type)
            self.server.budget.response(index, status, True)
        except Exception as error:
            arrival.update(status="refused_or_failed", error=repr(error))
            if "response_bytes" not in arrival:
                try:
                    self.server.budget.response(index, 409, False)
                    self.deliver(index, arrival, 409, canonical({"error": {"message": "fixture admission refused"}}).encode(), "application/json")
                    self.server.budget.response(index, 409, True)
                except Exception as write_error:
                    arrival["error_response_write_error"] = repr(write_error)
                arrival["status"] = "refused_or_failed"
        finally:
            arrival["finished_monotonic"] = time.monotonic()
            save(self.server.output / f"http-{index}-arrival.json", arrival)


def controller(protocol_path, output):
    protocol = load(protocol_path)
    verify_files(protocol["versions"])
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    initialization_start = time.perf_counter()
    from verifiers.v1.dialects.chat import ChatDialect
    dialect = ChatDialect()
    initialization_seconds = time.perf_counter() - initialization_start
    save(output / "fixture-initialization.json", {"seconds": initialization_seconds, "before_listen": True})
    processes, records, samples, restarts = [], [], [], []
    observer_seconds = 0.0
    current = server = thread = None
    stdout = stderr = None
    try:
        for phase in (1, 2, 3):
            # New listener and HttpBudget instance, same durable physical budget and logical ledger.
            server = RetryServer(output, protocol, dialect, records)
            before = server.budget.snapshot()
            assert len(before["arrivals"]) == 2 * (phase - 1)
            restarts.append({"phase": phase, "port": server.server_port, "before": before})
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            endpoint = f"http://127.0.0.1:{server.server_port}/v1"
            stdout = (output / f"worker-{phase}-stdout.log").open("xb")
            stderr = (output / f"worker-{phase}-stderr.log").open("xb")
            current = subprocess.Popen([sys.executable, __file__, "worker", str(protocol_path), str(output), str(phase), endpoint],
                                       stdout=stdout, stderr=stderr, start_new_session=True)
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
                samples.append({"monotonic": time.monotonic(), **{name: int(Path('/sys/fs/cgroup/' + filename).read_text())
                    for name, filename in [("memory_current", "memory.current"), ("pids_current", "pids.current")]}})
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
            assert len(snapshot["arrivals"]) == 2 * phase
            save(output / f"http-budget-phase-{phase}.json", snapshot)
            server = thread = None
        final = load(output / "worker-final.json")
        assert len({p["pid"] for p in processes}) == 3
        assert [r["status"] for r in final["attempts"]] == ["completed", "completed", "burned", "completed"]
        assert [r["reward"] for r in final["attempts"]] == [0.0, 1.0, None, 1.0]
        assert [r["response_status"] for r in records] == [503, 200, 503, 200, 503, 200]
        assert [r["attempt"] for r in records] == ["dev-bad", "dev-bad", "dev-good", "dev-good", "final-once", "final-once"]
        assert all(r["status"] == "delivered" and r["write_completed"] and r["slot"]["admitted"] for r in records)
        assert all(records[i]["request_sha256"] == records[i+1]["request_sha256"] for i in (0, 2, 4))
        assert final["metadata"]["winner"] == "fixture-good"
        assert load(output / "worker-2-start.json")["burned"] == 0
        assert load(output / "worker-3-start.json")["burned"] == 1
        result = {"status": "passed", "finite_scope": "actual native SDK transient retries; durable physical admission across three listeners and two worker reopens",
            "native_episodes": 3, "native_scores": 3, "provider_requests": 6, "injected_503": 3, "delivered_200": 3,
            "forced_kills": 2, "processes": processes, "development_reservations": 3, "completed_development": 2,
            "burned_development": 1, "final_reservations": 1, "fixture_final_reward": 1.0,
            "suite_seconds": time.perf_counter() - started}
    except BaseException as error:
        if current is not None and current.poll() is None:
            os.killpg(current.pid, signal.SIGKILL); current.wait(timeout=5)
        result = {"status": "failed", "error": repr(error), "processes": processes,
                  "provider_requests": len(records), "suite_seconds": time.perf_counter() - started, "no_retry": True}
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
        save(output / "listener-restarts.json", restarts)
        save(output / "resource-samples.json", samples)
    result.update(fixture_initialization_seconds=initialization_seconds, observer_read_seconds=observer_seconds,
        memory_peak_cgroup_bytes=int(Path('/sys/fs/cgroup/memory.peak').read_text()),
        request_body_bytes=sum(r["request_bytes"] for r in records),
        response_body_bytes=sum(r.get("response_bytes", 0) for r in records), limitations=protocol["limitations"])
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
