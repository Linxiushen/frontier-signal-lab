"""Independent complete-directory acceptance for separately frozen caller v3.

Composes the exact complete raw schema with unchanged v2 identity, provider,
training, ledger and cleanup checks. This does not reclassify the v2 outcome.
Only saved bytes are parsed: no producer import, process launch or ML execution.
"""
import argparse
import json
from pathlib import Path

from scripts import audit_training_ledger_v2 as saved
from scripts import check_training_ledger_v2_preservation as schema

ROOT=Path(__file__).resolve().parents[1]


def audit_cases(report,output,freeze):
    """Replay the complete directory before the original payload sub-contract."""
    assert {p.name for p in output.iterdir()}=={'report.json','healthy','partial_pretrain'},'suite directory schema differs'
    assert report['passed'] is True and [c['id']for c in report['cases']]==['healthy','partial_pretrain']
    start,end=report['started_perf_counter'],report['completed_perf_counter']
    started,completed=saved.stamp(report['started_at']),saved.stamp(report['completed_at'])
    assert 0<=end-start<=240 and abs((completed-started).total_seconds()-(end-start))<=0.25
    h,f=report['cases'];assert h['completed_perf_counter']<=f['started_perf_counter']
    full,original=schema.payload_sets(h,output/'healthy')
    checks=saved.healthy(h,freeze,original,start,end,started,completed)
    assert all(c['passed']for c in checks),[c for c in checks if not c['passed']]
    fault_full,_=schema.payload_sets(f,output/'partial_pretrain')
    assert saved.fault_checks(f,h,output/'partial_pretrain',freeze)
    # Fault-only before/accepted receipts are absent from the incomplete parent
    # brackets. Validate their envelope/counter and ordered acceptance directly.
    previous=f['started_perf_counter'];wid=f['worker_identity']['self_receipt']
    for i,row in enumerate(f['controller_controls']):
        name=row['filename'].replace('.json','-accepted.json');value=fault_full[name]
        assert set(value)=={'nonce','role','pid','filename','control_envelope','accepted_perf_counter','next_control_index'}
        assert value['role']=='worker' and value['filename']==row['filename'] and value['next_control_index']==i+1
        assert type(value['next_control_index'])is int and value['nonce']==f['nonce'] and value['pid']==wid['pid']
        instant=value['accepted_perf_counter']
        assert saved.finite(instant) and previous<=row['emitted_perf_counter']<=instant<=f['completed_perf_counter']
        previous=instant
    progress={c['id']:saved.audit_progress(c,output/c['id'],freeze)for c in (h,f)}
    ledger={c['id']:saved.ledger_checks(c,(output/c['id']/'trace.jsonl').read_bytes())for c in (h,f)}
    return {'passed':True,'complete_directory_schema':True,'raw_json_files':{'healthy':len(full),'partial_pretrain':len(fault_full)},
        'healthy_original_payload_checks':len(checks),'import_progress':progress,'ledger':ledger,
        'model_loads':2,'optimizer_updates':16,'scientific_experiments':1,
        'retained_exits':sum(len(c['cleanup']['exit_codes'])for c in (h,f)),
        'empty_jobs':sum(c['cleanup']['job_active_count']==0 for c in (h,f)),
        'boundary':'Local CPU actual-caller integration; no matched cost, full peak, quality, GPU, distributed or production validation.'}


def audit_files(output,protocol_path,freeze_path,root=ROOT):
    report=json.loads((output/'report.json').read_bytes());protocol=json.loads(protocol_path.read_bytes());freeze=json.loads(freeze_path.read_bytes())
    assert report['id']==protocol['id']=='actual-pretrained-training-ledger-v3'
    assert report['protocol_sha256']==freeze['protocol_sha256']==schema.sha(protocol_path)
    assert report['freeze_sha256']==schema.sha(freeze_path)
    assert all(schema.sha(root/p)==h for p,h in freeze['source_sha256'].items())
    assert protocol['limits']==saved.LIMITS and protocol['training_config']==saved.CONFIG
    assert protocol['sampled_private_byte_stop']==1073741824 and protocol['cases']==['healthy','partial_pretrain']
    assert freeze['actual_suites_permitted']==1 and freeze['retries']==0
    assert freeze['model_loads_ceiling']==2 and freeze['optimizer_updates_ceiling']==16
    assert saved.stamp(protocol['predeclared_at'])<=saved.stamp(freeze['frozen_at'])<=saved.stamp(report['started_at'])
    return audit_cases(report,output,freeze)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('output','protocol','freeze'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(audit_files(a.output,a.protocol,a.freeze),indent=2))
