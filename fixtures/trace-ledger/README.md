# Thread ledger fixture

This original standard-library component serializes sequence assignment, encoded
byte admission, write, flush and committed-state publication under one lock.
It is an engineering prerequisite for a future observer; the native observer
does not yet use it. Earlier rejected native traces remain unchanged.

Verify the recorded seven-arm experiment without running the producer:

```bash
python -S -B experiments/audit_trace_ledger.py --protocol fixtures/trace-ledger/protocol.json --result-dir results/trace-ledger --implementation fixtures/trace-ledger/implementation.json --source-root .
```

Run the finite unit controls separately:

```bash
python -S -B -m unittest discover -s tests -p test_trace_ledger.py -v
```

In a fresh checkout, execute the frozen protocol once:

```bash
python -S -B experiments/trace_ledger_probe.py --protocol fixtures/trace-ledger/protocol.json --output reports/runs/20261019T092118Z/trace-ledger-probe --freeze fixtures/trace-ledger/implementation.json
```

The output directory must be absent. A later reproduction uses a new output
directory and a separately saved copy of the implementation freeze with only
`output_directory` changed; retain that new freeze and its hash. Do not overwrite
old traces. Seed 20261019 fixes input IDs, not thread scheduling, admission order
or output hashes. The read-only auditor can audit a new run with its new freeze.

Each ledger exclusively owns one initially empty binary sink in one process.
A committed row means an exact write acknowledgment and successful flush.
Partial/failed writes and failed flushes poison the ledger permanently; an
uncertain tail is retained and never retried or promoted into the committed
prefix. Recursive calls reject explicitly. The component does not supply
fsync/power-loss durability, multiprocess coordination or hard deadlines for
arbitrary blocking sinks. Caps bound admitted UTF-8 bytes, not temporary
serialization memory. The five-second joins and ten-second suite ceiling apply
to this cooperative in-memory fixture only.

No Node, SDK, model, provider or network target runs in this experiment. Passing
this fixture does not establish production liveness, repair old topology or
events, or change H1/H2/H3/H4 scientific status.
