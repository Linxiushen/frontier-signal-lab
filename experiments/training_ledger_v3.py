"""Same actual pretrained caller with a separately frozen complete-directory audit.

Producer, worker, ledger, deadlines, provider, roles and cleanup are unchanged.
No model runs on import. Version 1/2 frozen outcomes remain immutable.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from experiments import training_ledger_v2 as previous
from experiments.training_ledger_v2 import (
    ROOT, CONFIG, CASES, LIMITS, MAX_PRIVATE_BYTES, obs, dual, prior, cost, base, duty,
    run_case,
)

ID="actual-pretrained-training-ledger-v3"
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,
    "scripts/check_training_ledger_v2_preservation.py",
    "experiments/training_ledger_v3.py",
    "scripts/audit_training_ledger_v3.py",
    "tests/test_training_ledger_v3.py")))


def run(protocol_path,freeze_path,output,plan):
    protocol,freeze=obs.read_small(protocol_path),obs.read_small(freeze_path)
    paths={k:Path(v).resolve() for k,v in plan["explicit_local_executable_paths"].items()}
    provider,model,fixture=(Path(plan[k]).resolve() for k in ("provider_source","model_dir","fixture"))
    assert protocol["id"]==ID and protocol["cases"]==list(CASES) and protocol["limits"]==LIMITS
    assert protocol["training_config"]==CONFIG and protocol["worker_control_plan"]==[list(v) for v in duty.CONTROL_PLAN]
    assert protocol["sampled_private_byte_stop"]==MAX_PRIVATE_BYTES
    assert freeze["source_sha256"]=={p:obs.sha256_file(ROOT/p) for p in SOURCES}
    assert freeze["protocol_sha256"]==obs.sha256_file(protocol_path)
    assert freeze["output_directory"]==output.relative_to(ROOT).as_posix()
    assert freeze["actual_suites_permitted"]==1 and freeze["retries"]==0
    assert freeze["model_loads_ceiling"]==2 and freeze["optimizer_updates_ceiling"]==16
    assert freeze["executables_sha256"]=={k:obs.sha256_file(p) for k,p in paths.items()}
    assert freeze["executable_path_sha256"]=={k:dual.path_hash(p) for k,p in paths.items()}
    assert freeze["python_runtime_files"]=={k:obs.sha256_file(paths["base_python"].parent/k) for k in freeze["python_runtime_files"]}
    site_packages=provider.parent.parent.parent
    assert all(obs.sha256_file(site_packages/p)==v["sha256"] for p,v in freeze["selected_runtime_files"].items())
    assert freeze["provider_source_sha256"]==prior.PROVIDER_SOURCE_SHA256==prior.source_digest(provider)
    assert freeze["provider_source_path_sha256"]==dual.path_hash(provider)
    assert Path(provider).parts[-3:]==("urllib3","util","connection.py")
    assert fixture==(ROOT/"fixtures/activation-cost").resolve()
    cost.verify_model_assets(model);cost.validate_fixture(fixture,verify_holdout=False)
    system32=Path(os.environ["SystemRoot"])/"System32"
    assert paths["native"]==(system32/"cmd.exe").resolve() and paths["conhost"]==(system32/"conhost.exe").resolve()
    assert datetime.fromisoformat(protocol["predeclared_at"])<=datetime.fromisoformat(freeze["frozen_at"])<datetime.now(timezone.utc)
    assert os.name=="nt"
    output.mkdir(exist_ok=False)
    start=time.perf_counter();end=start+240
    report={"id":ID,"started_at":base.utc_now(),"started_perf_counter":start,
        "protocol_sha256":obs.sha256_file(protocol_path),"freeze_sha256":obs.sha256_file(freeze_path),
        "cases":[],"scientific_experiments":1,"model_loads_ceiling":2,"optimizer_updates_ceiling":16}
    for spec in CASES:
        report["cases"].append(run_case(spec,paths,provider,model,fixture,freeze,output,end))
        if not report["cases"][-1]["passed"]:break
    report["passed"]=len(report["cases"])==2 and all(c["passed"] for c in report["cases"]) and time.perf_counter()<=end
    report["completed_at"]=base.utc_now();report["completed_perf_counter"]=time.perf_counter()
    obs.write_new(output/"report.json",report)
    print(json.dumps({"passed":report["passed"],"cases":[(c["id"],c["passed"])for c in report["cases"]]}))
    return report["passed"]


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("protocol","freeze","output","plan"):
        parser.add_argument("--"+name,type=Path,required=True)
    a=parser.parse_args()
    raise SystemExit(0 if run(a.protocol.resolve(),a.freeze.resolve(),a.output.resolve(),obs.read_small(a.plan)) else 1)
