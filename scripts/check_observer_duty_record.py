"""Post-outcome preservation of one REJECTED observer-duty study.

This checker was written after seeing the outcome. It is not preregistered
acceptance and cannot upgrade the unchanged frozen auditor's four rejections.
It reads saved bytes and replays the frozen stdlib auditor only; no workload,
ML imports, native process, socket or provider operation is performed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if not __package__:sys.path.insert(0,str(ROOT))
from scripts import audit_observer_duty as frozen

REPORT_SHA256='1b838a380db6ef6cef8b025c678d68d4d6e124b05e1f2229dc04711cc535de3a'
PROTOCOL_SHA256='759d841360550416d9f000a82d6449dffb577a37c8e6e42c5875741c3e4601cd'
FREEZE_SHA256='7f054ebaba39db23180e792535fcbd8e8a7a65c197e3f8bff4c31e7ea75a07a6'
AUDIT_SHA256='c372741cf68ddd7c3d3450ce0fb66e550eca1e3160ffe9f43e9fa44712e15f6d'
AUDITOR_SHA256='c4ee4fa690db672c72e4837d14f16dd48422ae0bdc9f7f404907ef39f5726252'
AUDITOR_TEST_SHA256='66b451dbd151792f0bcb4af51e6855b7845670563abec8bcc4c3a30700bfce89'
RAW_INVENTORY_SHA256='4a53a55fe32a3dd56ec5969aae8b7f89568ae822f01dc1076ae2c722d21c6ac3'
EXPECTED_FAILURES=[name+':exact_worker_native_prefinish_liveness' for name,_ in frozen.CASES]
EXPECTED_CHECK_COUNT=5528


def sha(value):return hashlib.sha256(value).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def check_record(report,saved_audit,recomputed,hashes):
    """Preserve known rejection plus byte custody; never reinterpret acceptance."""
    checks=[];timings=[]
    def check(value,name):checks.append({'check':name,'passed':bool(value)})
    try:
        for key,pin in [('report',REPORT_SHA256),('protocol',PROTOCOL_SHA256),('freeze',FREEZE_SHA256),
            ('audit',AUDIT_SHA256),('auditor',AUDITOR_SHA256),('auditor_tests',AUDITOR_TEST_SHA256),
            ('raw_inventory',RAW_INVENTORY_SHA256)]:
            check(hashes[key]==pin,'exact_original_'+key+'_bytes')
        check(hashes['sources']==frozen.SOURCE_HASHES,'exact_frozen_producer_sources')
        check(hashes['dependencies']==frozen.DEPENDENCY_HASHES,'exact_historical_dependencies')
        check(hashes['raw_count']==176 and hashes['raw_files_only'] is True,'exact_176_raw_JSON_files_no_extras')
        check(report['experiment_id']==frozen.EXPERIMENT and report['passed'] is True,
            'original_producer_success_claim_preserved_not_joint_acceptance')
        check(report['protocol_sha256']==PROTOCOL_SHA256 and report['implementation_sha256']==FREEZE_SHA256,
            'original_protocol_implementation_chain')
        for label,value in [('saved',saved_audit),('recomputed',recomputed)]:
            check(value['passed'] is False and value['receipt_consistency_passed'] is False,
                label+'_frozen_auditor_still_rejects')
            check(value['check_count']==EXPECTED_CHECK_COUNT and value['checks_passed']==EXPECTED_CHECK_COUNT-4 and
                value['failures']==EXPECTED_FAILURES,label+'_exact_unchanged_four_rejections_and_counts')
            check(value['root_freeze_pins_set'] is True,label+'_frozen_pins_enforced')
        check(canonical(saved_audit['checks'])==canonical(recomputed['checks']),
            'frozen_checks_replayed_exactly_no_new_or_removed_acceptance_checks')
        cases=report['cases']
        check([(c['id'],c['sampling_enabled']) for c in cases]==list(frozen.CASES),'original_ABBA_inventory')
        for case in cases:
            cid=case['id'];emit=case['controller_controls'][10]['emitted_perf_counter']
            accepted=case['worker_controls'][10]['accepted_perf_counter'];finish=case['controller_controls'][11]['emitted_perf_counter']
            live=case['prefinish_live_members'];clocks=[row['verified_perf_counter'] for row in live]
            check(len(live)==2 and all(row['alive'] is True and row['job_member'] is True for row in live) and
                emit<=min(clocks)<=max(clocks)<=finish<accepted,
                cid+':observed_parent_release_live_finish_before_worker_acceptance_preserved')
            check(case['passed'] is True and case['outcome']=='normal_completion' and
                case['cleanup']['job_active_count']==0 and len(case['cleanup']['exit_codes'])==5 and
                all(row['exit_code']==0 for row in case['cleanup']['exit_codes']),cid+':original_normal_exit_evidence')
            timings.append({'id':cid,'continue_emitted':emit,'continue_accepted':accepted,
                'prefinish_live_verified':clocks,'finish_emitted':finish,
                'continue_accept_after_live_seconds':[accepted-clock for clock in clocks]})
    except (KeyError,ValueError,TypeError,AttributeError,IndexError,OverflowError) as error:
        check(False,'invalid_or_incomplete_saved_record:'+type(error).__name__)
    failures=[row['check'] for row in checks if not row['passed']]
    return {'schema_version':1,'record_preservation_checks_passed':not failures,'experiment_acceptance_passed':False,
        'frozen_success_auditor_passed':False,'post_outcome_checker':True,'preregistered_acceptance':False,
        'check_count':len(checks),'checks_passed':sum(row['passed'] for row in checks),'failures':failures,
        'checks':checks,'known_frozen_failures':list(EXPECTED_FAILURES),'prefinish_timing':timings,
        'original_report_sha256':REPORT_SHA256,'scope':__doc__}


def check_files(report_path,acceptance_audit_path,*,root=ROOT,protocol_path=None,freeze_path=None):
    root=Path(root);report_path=Path(report_path)
    protocol_path=Path(protocol_path) if protocol_path else root/'fixtures/observer-duty/protocol.json'
    freeze_path=Path(freeze_path) if freeze_path else root/'fixtures/observer-duty/implementation.json'
    rb,report=frozen.bounded(report_path,16*1048576);ab,saved_audit=frozen.bounded(acceptance_audit_path,16*1048576)
    pb,_=frozen.bounded(protocol_path);fb,_=frozen.bounded(freeze_path)
    raw={};raw_files_only=True
    for name,_ in frozen.CASES:
        folder=report_path.parent/name
        for path in folder.iterdir():
            relative=path.relative_to(report_path.parent).as_posix()
            if not path.is_file() or path.suffix!='.json':
                raw_files_only=False;raw[relative]='unexpected-file-or-directory';continue
            content,_=frozen.bounded(path);raw[relative]=sha(content)
    hashes={'report':sha(rb),'protocol':sha(pb),'freeze':sha(fb),'audit':sha(ab),
        'auditor':sha((root/'scripts/audit_observer_duty.py').read_bytes()),
        'auditor_tests':sha((root/'tests/test_observer_duty_auditor.py').read_bytes()),
        'sources':{p:sha((root/p).read_bytes()) for p in frozen.SOURCE_PATHS},
        'dependencies':{p:sha((root/p).read_bytes()) for p in frozen.DEPENDENCY_PATHS},
        'raw_inventory':sha(canonical(raw).encode()),'raw_count':len(raw),'raw_files_only':raw_files_only}
    try:recomputed=frozen.audit_files(report_path,protocol_path,freeze_path,root=root)
    except (KeyError,ValueError,TypeError,OSError) as error:recomputed={'replay_error':type(error).__name__}
    return check_record(report,saved_audit,recomputed,hashes)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=ROOT/'results/observer-duty/report.json')
    parser.add_argument('--acceptance-audit',type=Path,default=ROOT/'results/observer-duty/frozen-audit.json')
    parser.add_argument('--protocol',type=Path);parser.add_argument('--freeze',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:result=check_files(args.report,args.acceptance_audit,protocol_path=args.protocol,freeze_path=args.freeze)
    except (KeyError,ValueError,TypeError,OSError) as error:
        result={'record_preservation_checks_passed':False,'experiment_acceptance_passed':False,'check_count':1,
            'checks_passed':0,'failures':['unreadable_saved_record:'+type(error).__name__]}
    if args.output:
        with args.output.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(result,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('record_preservation_checks_passed','experiment_acceptance_passed',
        'check_count','checks_passed','failures')}))
    return 0 if result['record_preservation_checks_passed'] and result['experiment_acceptance_passed'] is False else 1


if __name__=='__main__':raise SystemExit(main())
