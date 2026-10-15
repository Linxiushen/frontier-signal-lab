"""Offline protocol model: explicit crash cuts, replay, and recovery contracts.

These are intentionally small protocols, not implementations or reproductions of
pi, OpenClaw, or verifiers. Atomic durable writes and fail-stop crashes are model
assumptions. In particular, no protocol saves a message crashed before persistence.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path


METRICS = (
    "acknowledged_message_loss", "stale_context", "duplicate_effect",
    "resurrected_retry", "missing_failure_evidence",
)
SOURCES = [
    "https://github.com/earendil-works/pi/issues/10979",
    "https://github.com/earendil-works/pi/issues/10982",
    "https://github.com/openclaw/openclaw/pull/173018",
    "https://github.com/PrimeIntellect-ai/verifiers/pull/2857",
]


class Protocol:
    """Naive callback-before-persist protocol with volatile lifecycle metadata."""

    name = "naive_callback_before_persist"
    message_plan = ("generate", "ack", "hook", "persist")

    def __init__(self):
        self.disk = {
            "messages": {}, "context_version": 0, "effects": [],
            "assignments": {}, "receipts": [], "failures": [], "score": None,
        }
        self.pending = None
        self.blocked = False
        self.compacting = False
        self.context_version = 0
        self.turns = {}
        self.queued = []
        self.assignments = {}
        self.trial = None
        # Oracle represents external observations, not recoverable agent memory.
        self.oracle = {"generated": [], "acknowledged": [], "terminal": [], "failures": []}
        self.violations = Counter()
        self.trace = []

    def event(self, action, **data):
        before = copy.deepcopy(self.disk)
        getattr(self, "on_" + action)(**data)
        self.trace.append({
            "index": len(self.trace), "action": action, "data": copy.deepcopy(data),
            "durable_before": before, "durable_after": copy.deepcopy(self.disk),
            "volatile": {"pending": self.pending, "blocked": self.blocked,
                         "compacting": self.compacting, "context_version": self.context_version,
                         "turns": copy.deepcopy(self.turns), "queued": list(self.queued)},
        })

    def on_generate(self, message="m1"):
        self.pending = message
        self.oracle["generated"].append(message)

    def on_ack(self):
        if self.blocked or self.pending is None:
            return
        self.oracle["acknowledged"].append(self.pending)

    def on_hook(self, hangs=False):
        self.blocked = hangs

    def on_persist(self):
        if not self.blocked and self.pending is not None:
            self.disk["messages"][self.pending] = "assistant result"

    def on_crash(self):
        self.pending = None
        self.blocked = False
        self.compacting = False
        self.turns = {}
        self.queued = []
        self.trial = None
        self.assignments = {}

    def on_restart(self):
        self.context_version = self.disk["context_version"]
        self.assignments = copy.deepcopy(self.disk["assignments"])

    def on_compact_start(self):
        self.compacting = True

    def on_turn_start(self, turn="t1"):
        self.turns[turn] = self.context_version

    def on_compact_finish(self):
        self.context_version += 1
        self.disk["context_version"] = self.context_version
        self.compacting = False

    def on_turn_commit(self, turn="t1"):
        version = self.turns.pop(turn)
        if version != self.context_version:
            self.violations["stale_context"] += 1

    def on_child_complete(self, child_turn="child1:turn1"):
        # No deduplication: a repeated notification repeats its external effect.
        if child_turn in self.disk["effects"]:
            self.violations["duplicate_effect"] += 1
        self.disk["effects"].append(child_turn)

    def on_assign(self, child_turn="child1:turn1"):
        self.disk["assignments"][child_turn] = "pending"
        self.assignments[child_turn] = "pending"

    def on_give_up(self, child_turn="child1:turn1"):
        self.assignments.pop(child_turn, None)
        self.oracle["terminal"].append(child_turn)

    def on_retry(self, child_turn="child1:turn1"):
        if self.assignments.get(child_turn) == "pending":
            if child_turn in self.oracle["terminal"]:
                self.violations["resurrected_retry"] += 1

    def on_score_start(self, attempt="a1"):
        self.trial = {"attempt": attempt, "diagnostics": {}}

    def on_score_diagnostic(self, reason="timeout"):
        self.trial["diagnostics"]["reason"] = reason

    def on_score_fail(self):
        self.oracle["failures"].append(copy.deepcopy(self.trial))
        self.trial = None

    def on_score_success(self, value=1):
        self.disk["score"] = value
        self.trial = None

    def metrics(self):
        result = {key: self.violations[key] for key in METRICS}
        result["acknowledged_message_loss"] = len(
            set(self.oracle["acknowledged"]) - self.disk["messages"].keys()
        )
        saved_failures = {f["attempt"] for f in self.disk["failures"]}
        result["missing_failure_evidence"] = sum(
            f["attempt"] not in saved_failures for f in self.oracle["failures"]
        )
        return result


class DurableLog(Protocol):
    """Persist message atomically before acknowledgement or extension hooks."""

    name = "durable_log_persist_before_hook"
    message_plan = ("generate", "persist", "ack", "hook")

    def on_ack(self):
        if self.pending in self.disk["messages"]:
            super().on_ack()


class VersionedJournal(DurableLog):
    """Adds queued compaction, durable idempotency, tombstones and diagnostics."""

    name = "versioned_idempotent_journal"

    def on_turn_start(self, turn="t1"):
        if self.compacting:
            self.queued.append(turn)
        else:
            super().on_turn_start(turn)

    def on_compact_finish(self):
        super().on_compact_finish()
        for turn in self.queued:
            self.turns[turn] = self.context_version
        self.queued = []

    def on_turn_commit(self, turn="t1"):
        # Compare-and-commit: reject an old snapshot rather than apply its effect.
        if self.turns[turn] != self.context_version:
            self.turns.pop(turn)
            return
        super().on_turn_commit(turn)

    def on_child_complete(self, child_turn="child1:turn1"):
        if child_turn not in self.disk["receipts"]:
            # This pair is one atomic durable transaction in this model.
            self.disk["effects"].append(child_turn)
            self.disk["receipts"].append(child_turn)

    def on_give_up(self, child_turn="child1:turn1"):
        self.disk["assignments"][child_turn] = "retired"
        self.assignments[child_turn] = "retired"
        self.oracle["terminal"].append(child_turn)

    def on_score_fail(self):
        self.disk["failures"].append(copy.deepcopy(self.trial))
        super().on_score_fail()


PROTOCOLS = (Protocol, DurableLog, VersionedJournal)


def replay(protocol_type, events):
    protocol = protocol_type()
    for event in events:
        protocol.event(event["action"], **event.get("data", {}))
    return protocol


def message_events(protocol_type, crash_after=None, hangs=False):
    """Cuts after each actual step; never persists skipped post-crash steps."""
    events = []
    if crash_after == 0:
        return [{"action": "crash"}, {"action": "restart"}]
    for index, action in enumerate(protocol_type.message_plan, 1):
        event = {"action": action}
        if action == "hook":
            event["data"] = {"hangs": hangs}
        events.append(event)
        if index == crash_after or (action == "hook" and hangs):
            events.extend([{"action": "crash"}, {"action": "restart"}])
            break
    return events


def scenarios(protocol_type):
    # Every boundary of each protocol's message transaction, including pre-gen.
    for cut in range(len(protocol_type.message_plan) + 1):
        yield f"message_crash_cut_{cut}", message_events(protocol_type, crash_after=cut)
    yield "message_no_fault", message_events(protocol_type)
    yield "hook_hangs_then_restart", message_events(protocol_type, hangs=True)
    yield "compaction_overlap", [
        {"action": "compact_start"}, {"action": "turn_start"},
        {"action": "compact_finish"}, {"action": "turn_commit"},
    ]
    yield "duplicate_completion_after_restart", [
        {"action": "child_complete"}, {"action": "crash"},
        {"action": "restart"}, {"action": "child_complete"},
        {"action": "child_complete", "data": {"child_turn": "child1:turn2"}},
    ]
    yield "terminal_retry_after_restart", [
        {"action": "assign"}, {"action": "give_up"}, {"action": "crash"},
        {"action": "restart"}, {"action": "retry"},
    ]
    yield "scoring_failure_then_success", [
        {"action": "score_start"}, {"action": "score_diagnostic"},
        {"action": "score_fail"}, {"action": "crash"}, {"action": "restart"},
        {"action": "score_start", "data": {"attempt": "a2"}},
        {"action": "score_success"},
    ]


def run_probe():
    rows = []
    for protocol_type in PROTOCOLS:
        for name, events in scenarios(protocol_type):
            model = replay(protocol_type, events)
            rows.append({
                "protocol": model.name, "scenario": name,
                "metrics": model.metrics(), "events": events, "trace": model.trace,
                "oracle": model.oracle,
                "unacknowledged_message_loss": len(
                    set(model.oracle["generated"]) - set(model.oracle["acknowledged"])
                    - model.disk["messages"].keys()
                ),
            })
    totals = {p.name: {key: sum(r["metrics"][key] for r in rows if r["protocol"] == p.name)
                       for key in METRICS} for p in PROTOCOLS}
    return {"schema_version": 1, "sources": SOURCES, "assumptions": [
        "Synthetic protocols; no upstream implementation is executed or reproduced.",
        "Single-process fail-stop crashes; durable writes are atomic and never torn.",
        "The versioned receipt and effect update is atomic in one local store; external exactly-once effects require their own transaction or idempotency key.",
        "Only acknowledged messages are covered by the loss metric. All protocols may lose generated messages crashed before persistence.",
        "A stale turn means committing after compaction using the previous context version.",
        "Scoring failure evidence is required only after an observed score_fail event; a pre-journal crash has no magical evidence recovery.",
        "Counts summarize this finite deterministic scenario suite; they are not real-world failure rates or model capability scores.",
    ], "totals": totals, "runs": rows}


def write_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "probe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    trace_dir = output / "counterexamples"
    trace_dir.mkdir(exist_ok=True)
    failures = [r for r in report["runs"] if any(r["metrics"].values())]
    for row in failures:
        path = trace_dir / f'{row["protocol"]}--{row["scenario"]}.json'
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = ["# Recovery contract probe", "", "Deterministic offline state-machine fault injection. Results follow the explicit protocol assumptions; they do not reproduce upstream bugs.", "",
             "| Protocol | ACK loss | Stale context | Duplicate effect | Retry resurrection | Missing failed-score evidence |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, counts in report["totals"].items():
        lines.append("| " + name + " | " + " | ".join(str(counts[k]) for k in METRICS) + " |")
    lines += ["", "These are violation counts across enumerated traces, not estimated probabilities. Crash cuts are protocol-local boundaries, so identical cut numbers need not describe identical actions.", "", "## Model boundaries", ""]
    lines += ["- " + assumption for assumption in report["assumptions"]]
    lines += ["", "All protocols lose the unacknowledged message at the post-generation/pre-persistence cut. `unacknowledged_message_loss` is exported separately and excluded from ACK loss.", "", "Each run in `probe.json` includes input events, durable before/after snapshots, volatile context, and an external observation oracle. Every observed contract failure also has a standalone JSON trace in `counterexamples/`.", "", "## Public inspiration (reports/proposals, not reproduced defects)", ""]
    lines += ["- " + url for url in SOURCES]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/recovery-contract"))
    args = parser.parse_args()
    report = run_probe()
    write_report(report, args.output)
    print(json.dumps(report["totals"], indent=2))


if __name__ == "__main__":
    main()
