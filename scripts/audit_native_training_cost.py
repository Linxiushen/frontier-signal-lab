"""Replay the native matched-cost receipts without loading Torch or a model."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments import native_training_cost as study


def read(path):return json.loads(path.read_bytes())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(output,*,checkpoints=True):
    r=read(output/'report.json');assert r['id']==study.ID
    rows=r['cases'];assert 1<=len(rows)<=12 and [c['job']for c in rows]==study.jobs()[:len(rows)]
    for c in rows:
        folder=output/c['id'];assert read(output/(c['id']+'-case.json'))==c
        assert read(folder/'job.json')==c['job']
        assert not list(folder.glob('*.pending'))
        if not c['passed']:
            assert c is rows[-1] and not r['passed'] and 'evaluation.json'not in [p.name for p in output.iterdir()]
            cleanup=c.get('failure_cleanup',c.get('cleanup',{}));assert cleanup['job_active_count']==0
            continue
        study.validate_case(copy.deepcopy(c))
        actual=c['worker_identity']['self_receipt'];native=c['native_descendant']['os_identity']
        ref=type('Identity',(),{'pid':actual['pid'],'creation_filetime':actual['creation_filetime']})()
        study.verify_controls(folder,copy.deepcopy(c),ref)
        study.prior.verify_cleanup(c,'healthy')
        for key,label in [('loop_before','before-loop.json'),('loop_after','after-loop.json')]:assert read(folder/label)==c[key]
        for label in study.duty.STAGES:
            assert read(folder/(label+'-ready.json'))==c['stages'][label]
            for k,suffix in [('self_before','before'),('self_after','after')]:
                assert read(folder/(label+'-'+suffix+'.json'))==c['memory_brackets'][label][k]
        raw=(folder/'trace.jsonl').read_bytes();lines=raw.splitlines(keepends=True)
        ledger=[json.loads(x)for x in lines]
        assert len(ledger)==c['ledger']['committed_rows'] and len(raw)==c['ledger']['committed_bytes']
        assert [x['seq']for x in ledger]==list(range(len(ledger)))
        assert ledger[0]['kind']=='bound' and ledger[-1]['kind']=='closed'
        samples=ledger[1:-1];expected=c['samples'][:3]+[x['sample']for x in c['active_window']['observations']]+c['samples'][3:]
        assert len(samples)==len(expected)
        for entry,sample in zip(samples,expected):
            assert entry['kind']=='sample' and entry['reading']==sample
            assert (entry['pid'],entry['creation_filetime'])==(actual['pid'],actual['creation_filetime'])
            assert entry['query_started_perf_counter']<=entry['member_verified_perf_counter']<=sample['perf_counter']<=entry['query_completed_perf_counter']<=entry['emitted_perf_counter']
        v=c['stages']['postvalidation']['validation']
        if checkpoints:assert sha(folder/'endpoint.pt')==v['checkpoint_sha256']
        # OS lifetime endpoint and actual self/parent identity are directly read
        # again here; this does not turn a sampled current-private maximum into peak.
        mem=c['memory_brackets']['postloop'];peak=mem['parent']['memory']['peak_resident_bytes']
        assert peak>=mem['parent']['memory']['resident_bytes']
        assert mem['self_before']['memory']['peak_resident_bytes']<=peak<=mem['self_after']['memory']['peak_resident_bytes']
        assert c['measurement']['actual_process_peak_resident_through_postloop_bytes']==peak
        assert c['healthy_completion']['optimizer_steps']==c['loop_after']['loop']['steps_completed']
    if r['passed']:
        assert len(rows)==12 and all(c['passed']for c in rows)
        release=read(output/'evaluation-release.json');evaluation=read(output/'evaluation.json')
        if checkpoints:study.validate_release(release,output)
        assert [e['job']for e in release['endpoints']]==study.jobs()
        assert evaluation['release_sha256']==sha(output/'evaluation-release.json')
        assert dt.datetime.fromisoformat(release['training_sealed_at'])<=dt.datetime.fromisoformat(evaluation['started_at'])
        assert evaluation['endpoints'] and len(evaluation['initial']['block_mean_nll'])==64
        for c,e,rel in zip(rows,evaluation['endpoints'],release['endpoints']):
            assert e['job']==rel['job']==c['job']
            assert e['checkpoint_sha256']==rel['checkpoint_sha256']==c['stages']['postvalidation']['validation']['checkpoint_sha256']
            assert len(e['evaluation']['block_mean_nll'])==64 and e['evaluation']['scored_target_positions']==4096
            assert e['evaluation']['mean_nll']==sum(e['evaluation']['block_mean_nll'])/64 or abs(e['evaluation']['mean_nll']-sum(e['evaluation']['block_mean_nll'])/64)<1e-12
        assert study.paired_results(rows,evaluation)==r['comparisons']
        assert r['evaluator']['passed'] and r['evaluator']['cleanup']['job_active_count']==0
    return {'receipt_integrity_passed':True,'execution_accepted':r['passed'],'cases':len(rows),
        'checkpoints_rehashed':checkpoints and r['passed'],'model_executions_in_auditor':0,
        'joint_screens_passed':r.get('comparisons',{}).get('all_six_joint_screens_passed')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--without-checkpoints',action='store_true');a=p.parse_args()
    print(json.dumps(audit(a.output,checkpoints=not a.without_checkpoints)))
