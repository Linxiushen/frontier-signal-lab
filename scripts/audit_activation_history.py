"""Standard-library-only result audit. Never imports model/experiment code."""
import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[1]
HISTORIES=('dense','model_except_norm_attention_saved_int8')
METHODS=('dense','model_except_norm_saved_int8','model_except_norm_attention_saved_int8')
SEEDS=(101,211,307)
POINTS=(4,8)
checks=Counter()
native_steps=Counter()
native_parameter_checks=Counter()


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check(category,label,condition):
    checks[category]+=1
    if not condition:
        raise AssertionError(category+':'+label)


def equal(category,label,actual,expected):
    check(category,label,actual==expected)


def near(category,label,actual,expected):
    check(category,label,isinstance(actual,(int,float)) and not isinstance(actual,bool)
          and math.isfinite(actual) and (actual==expected or math.isclose(actual,expected,rel_tol=2e-15,abs_tol=0)))


def tensor_hash(dtype,shape,payload):
    return digest({'dtype':dtype,'shape':shape,'data_sha256':hashlib.sha256(payload).hexdigest()})


def token_hash(rows):
    flat=[x for row in rows for x in row]
    return tensor_hash('int64',[len(rows),len(rows[0])],struct.pack('<'+'q'*len(flat),*flat))


zero_hash_cache={}
def zero_hash(shape):
    key=tuple(shape)
    if key not in zero_hash_cache:
        zero_hash_cache[key]=tensor_hash('float32',shape,bytes(4*math.prod(shape)))
    return zero_hash_cache[key]


def full_state(rows,which):
    return digest({r['name']:{k:r[which+'_sha256'][k] for k in ('parameter','exp_avg','exp_avg_sq')}|
                   {'step':r['input_step'] if which=='input' else r['optimizer_step']} for r in rows})


def moment_state(rows,which):
    return digest({r['name']:{k:r[which+'_sha256'][k] for k in ('exp_avg','exp_avg_sq')}|
                   {'step':r['input_step'] if which=='input' else r['optimizer_step']} for r in rows})


def named_hash(rows,which,key):
    return digest({r['name']:r[which+'_sha256'][key] for r in rows})


STAT_KEYS=('reference_sum_squares','candidate_sum_squares','difference_sum_squares','dot_product')


def metric(label,record,descriptive=False):
    for key in STAT_KEYS+('max_absolute_difference',):
        check('metric',label+':finite:'+key,isinstance(record[key],(int,float))
              and not isinstance(record[key],bool) and math.isfinite(record[key]))
    for key in ('reference_sum_squares','candidate_sum_squares','difference_sum_squares','max_absolute_difference'):
        check('metric',label+':nonnegative:'+key,record[key]>=0)
    rn,cn,dn=(math.sqrt(record[k])for k in STAT_KEYS[:3])
    for key,value in [('reference_l2',rn),('candidate_l2',cn),('difference_l2',dn)]:
        near('metric',label+':'+key,record[key],value)
    relative=dn/rn if rn else (None if descriptive or dn else 0.)
    cosine=max(-1.,min(1.,record['dot_product']/(rn*cn))) if rn and cn else (None if descriptive else (1. if rn==cn else 0.))
    for key,expected in [('relative_l2',relative),('cosine_similarity',cosine)]:
        if expected is None:
            equal('metric',label+':'+key,record[key],None)
        else:
            near('metric',label+':'+key,record[key],expected)
    if descriptive and rn==0:
        equal('metric',label+':relative_undefined',record['relative_l2_undefined_reason'],'zero dense reference norm')
    if descriptive and (rn==0 or cn==0):
        equal('metric',label+':cosine_undefined',record['cosine_undefined_reason'],'zero vector norm')
    check('metric',label+':l2_triangle',dn<=rn+cn+8*math.ulp(max(rn+cn,1e-300)))


def comparison(label,comparison,names,descriptive=False):
    rows=comparison['per_parameter'];aggregate=comparison['aggregate']
    equal('metric',label+':names',[r['name']for r in rows],names)
    for row in rows:
        metric(label+':'+row['name'],row,descriptive)
    for key in STAT_KEYS:
        equal('aggregate',label+':'+key,aggregate[key],math.fsum(row[key]for row in rows))
    equal('aggregate',label+':maximum',aggregate['max_absolute_difference'],max(row['max_absolute_difference']for row in rows))
    metric(label+':aggregate',aggregate,descriptive)


def checker(label,record,step,kind,names=None):
    equal('native',label+':all_checks_passed',record['all_checks_passed'],True)
    equal('native',label+':separate_rounding_control',record['rounding_control_is_not_scientific_fidelity_gate'],True)
    rows=record['per_parameter']
    equal('native',label+':tensors',len(rows),76)
    equal('native',label+':elements',sum(r['elements']for r in rows),14067712)
    equal('native',label+':unique_names',len({r['name']for r in rows}),76)
    if names is not None:
        equal('native',label+':ordered_names',[r['name']for r in rows],names)
    native_steps[kind]+=1
    for row in rows:
        prefix=label+':'+row['name']
        native_parameter_checks[kind]+=1
        equal('native',prefix+':counter',(row['input_step'],row['optimizer_step']),(step-1,step))
        equal('native',prefix+':shape',row['elements'],math.prod(row['shape']))
        equal('native',prefix+':gradient_unchanged',row['input_sha256']['gradient'],row['output_sha256']['gradient'])
        equal('native',prefix+':counter_input_hash',row['input_sha256']['step'],digest(step-1))
        equal('native',prefix+':counter_output_hash',row['output_sha256']['step'],digest(step))
        equal('native',prefix+':native_scalar_counter',row['output_sha256']['native_step_tensor'],tensor_hash('float32',[],struct.pack('<f',step)))
        for field,control in row['numpy_reference_parity'].items():
            equal('native',prefix+':'+field+':passed',control['passed'],True)
            check('native',prefix+':'+field+':bound',math.isfinite(control['max_fraction_of_allowed_error'])
                  and 0<=control['max_fraction_of_allowed_error']<=1)
            check('native',prefix+':'+field+':error',math.isfinite(control['max_absolute_error']) and control['max_absolute_error']>=0)
            if field=='parameter':
                check('native',prefix+':parameter_interval',control['max_interval_width']>0 and control['max_rounding_enlargement']>0)
            else:
                check('native',prefix+':moment_tolerance',control['max_allowed_error']>0)
        equal('native',prefix+':all_three_arithmetic_fields',set(row['numpy_reference_parity']),{'parameter','exp_avg','exp_avg_sq'})
    return rows


def gate(records):
    baseline,treatment=[r['update_comparison']['aggregate']for r in records[1:]]
    a,b=baseline['relative_l2'],treatment['relative_l2'];ca,cb=baseline['cosine_similarity'],treatment['cosine_similarity']
    finite=lambda x:x is not None and math.isfinite(x)
    ratio=b/a if finite(a)and finite(b)and a>0 and b>=0 else None
    absolute=finite(b)and b<=.1;direction=finite(cb)and cb>=.99
    dominance=ratio is not None and ratio<=.5 and finite(ca)and finite(cb)and cb>=ca
    return {'absolute_error_passed':absolute,'absolute_direction_passed':direction,'relative_dominance_passed':dominance,
            'treatment_to_norm_only_relative_l2_ratio':ratio,'passed':bool(absolute and direction and dominance)}


def gradient(label,g,method):
    equal('gradient',label+':method',g['method'],method)
    equal('gradient',label+':tensor_count',g['parameter_tensors_with_finite_gradients'],76)
    equal('gradient',label+':elements',g['parameter_elements_with_finite_gradients'],14067712)
    value=g['observed_vs_analytic_logits_gradient']['relative_l2']
    check('gradient',label+':exact_ce_analytic',value is not None and math.isfinite(value)and 0<=value<=1e-5)
    expected_norms={f'gpt_neox.layers.{i}.{which}_layernorm'for i in range(6)for which in ('input','post_attention')}|{'gpt_neox.final_layer_norm'}
    expected_attention={f'gpt_neox.layers.{i}.attention'for i in range(6)}
    equal('gradient',label+':norm_scopes',set(g['named_layernorm_saves']),expected_norms)
    equal('gradient',label+':attention_scopes',set(g['named_attention_saves']),expected_attention)
    equal('gradient',label+':norm_policy',g['layernorm_save_policy'],'dense')
    compressed=method=='model_except_norm_saved_int8'
    equal('gradient',label+':attention_policy',g['attention_save_policy'],'int8_saved_tensors'if compressed else'dense')
    for scope,inventory in g['named_layernorm_saves'].items():
        equal('gradient',label+':'+scope+':calls',inventory['calls'],1)
        counts=inventory['inventory']['counts']
        equal('gradient',label+':'+scope+':save_unpack',(counts['save_calls'],counts['unpack_calls']),(5,5))
        equal('gradient',label+':'+scope+':preserved',(counts.get('compressed_saves',0),counts.get('decoded_saves',0)),(0,0))
    for scope,inventory in g['named_attention_saves'].items():
        equal('gradient',label+':'+scope+':calls',inventory['calls'],1)
        counts=inventory['inventory']['counts'];expected=counts['eligible']if compressed else 0
        equal('gradient',label+':'+scope+':save_unpack',(counts['save_calls'],counts['unpack_calls']),(13,13))
        equal('gradient',label+':'+scope+':saved_policy',(counts.get('compressed_saves',0),counts.get('decoded_saves',0)),(expected,expected))


def stable_gradient(record):
    omitted={'timing_seconds_descriptive_only','saved_tensor_inventory','named_layernorm_saves','named_attention_saves'}
    return {k:v for k,v in record.items()if k not in omitted}


def stable_worker(w):
    omitted={'pid','started_at','completed_at','wall_seconds_descriptive_only','runtime','parent_wall_seconds_descriptive_only','worker_file_sha256'}
    clean={k:v for k,v in w.items()if k not in omitted};clean['histories']={}
    for h,item in w['histories'].items():
        history={k:v for k,v in item.items()if k not in ('steps','anchors')}
        history['steps']=[{**s,'gradient_diagnostic':stable_gradient(s['gradient_diagnostic'])}for s in item['steps']]
        history['anchors']=[{**a,'gradients':[stable_gradient(g)for g in a['gradients']]}for a in item['anchors']]
        clean['histories'][h]=history
    return clean


def audit(result, output):
    """Verify published receipts without executing or importing experiment code.

    Output must be a new file, so an audit cannot overwrite its inputs.
    Relative paths resolve against the caller's current working directory.
    """
    RESULT=Path(result).resolve()
    OUT=Path(output).resolve()
    if OUT.exists():
        raise FileExistsError('Fresh audit output file required: '+str(OUT))
    checks.clear()
    native_steps.clear()
    native_parameter_checks.clear()
    zero_hash_cache.clear()
    protocol_path=ROOT/'fixtures/activation-history/protocol.json';freeze_path=ROOT/'fixtures/activation-history/implementation.json'
    protocol=read(protocol_path);freeze=read(freeze_path);config=protocol['config']
    equal('pin','protocol_file',sha(protocol_path),'612b12f3c013822ac0074b4920544ac5c2e3c0bbeef545bae7056ecbd5076fa4')
    equal('pin','protocol_config',digest(config),protocol['config_sha256'])
    equal('pin','freeze_protocol',freeze['protocol_sha256'],sha(protocol_path))
    equal('pin','freeze_payload',freeze['receipt_sha256'],digest({k:v for k,v in freeze.items()if k!='receipt_sha256'}))
    equal('pin','freeze_dependencies',freeze['frozen_dependencies_sha256'],protocol['frozen_dependencies_sha256'])
    for path,expected in freeze['new_source_files_sha256'].items():equal('pin','new_source:'+path,sha(ROOT/path),expected)
    for path,expected in protocol['frozen_dependencies_sha256'].items():equal('pin','dependency:'+path,sha(ROOT/path),expected)
    for path,expected in protocol['prior_results_sha256'].items():equal('pin','prior_result:'+path,sha(ROOT/path),expected)
    data_path=ROOT/'fixtures/activation-history/data.json';manifest_path=ROOT/'fixtures/activation-history/manifest.json'
    equal('pin','data',sha(data_path),protocol['data_sha256']);equal('pin','manifest',sha(manifest_path),protocol['manifest_sha256'])
    data=read(data_path);manifest=read(manifest_path)
    for split in ('train','audit'):equal('pin','source:'+split,sha(manifest_path.parent/manifest['sources'][split]['file']),manifest['sources'][split]['sha256'])
    report_path=RESULT/'report.json'
    if not report_path.is_file():
        incomplete_path=RESULT/'incomplete.json'
        if incomplete_path.is_file():
            incomplete=read(incomplete_path)
            equal('incomplete','not_scientific_outcome',incomplete['scientific_gate_outcome'],None)
            raise RuntimeError('Engineering incomplete; not a valid scientific gate failure: '+canonical(incomplete))
        raise FileNotFoundError('Awaiting complete result report; audit performs no model execution.')
    report=read(report_path);stable=report['stable_results'];workers=report['worker_measurements']
    equal('report','completed',report['completed'],True)
    equal('report','config',report['config'],config)
    equal('report','stable_digest',digest(stable),report['stable_result_sha256'])
    equal('report','observation_digest',digest({k:v for k,v in report.items()if k!='observation_sha256'}),report['observation_sha256'])
    equal('report','no_incomplete', (RESULT/'incomplete.json').exists(),False)
    equal('report','ordered_seeds',[w['seed']for w in workers],list(SEEDS))
    check('chronology','protocol_before_freeze',dt.datetime.fromisoformat(protocol['predeclared_at'])<=dt.datetime.fromisoformat(freeze['frozen_at']))
    first_states=[];all_gates=[];exact=[];drift_summary=[];raw_worker_receipts=[];previous_completion=None
    for w in workers:
        seed=w['seed'];prefix='seed-'+str(seed);path=RESULT/'workers'/prefix/'worker.json';raw=read(path)
        equal('report',prefix+':raw_sha',sha(path),w['worker_file_sha256'])
        equal('report',prefix+':raw_projection',raw,{k:v for k,v in w.items()if k not in ('parent_wall_seconds_descriptive_only','worker_file_sha256')})
        raw_worker_receipts.append({'seed':seed,'sha256':sha(path),'bytes':path.stat().st_size})
        equal('worker',prefix+':complete',w['completed'],True)
        equal('worker',prefix+':storage_disjoint',w['histories_storage_disjoint'],True)
        equal('worker',prefix+':histories_order',list(w['histories']),list(HISTORIES))
        equal('worker',prefix+':schedule_sha',w['schedule_sha256'],protocol['schedules'][str(seed)]['history_batches_sha256'])
        for key,expected in [('protocol_sha256',sha(protocol_path)),('implementation_freeze_sha256',sha(freeze_path)),('config_sha256',protocol['config_sha256'])]:equal('pin',prefix+':'+key,w[key],expected)
        check('chronology',prefix+':freeze_then_execution',dt.datetime.fromisoformat(freeze['frozen_at'])<=dt.datetime.fromisoformat(w['started_at'])<dt.datetime.fromisoformat(w['completed_at']))
        if previous_completion:check('chronology',prefix+':sequential_workers',dt.datetime.fromisoformat(previous_completion)<=dt.datetime.fromisoformat(w['started_at']))
        previous_completion=w['completed_at']
        check('budget',prefix+':worker',0<w['wall_seconds_descriptive_only']<=900)
        check('budget',prefix+':parent',0<w['parent_wall_seconds_descriptive_only']<=960)
        for key,expected in [('threads',1),('device','cpu'),('deterministic_algorithms',True)]:equal('runtime',prefix+':'+key,w['runtime'][key],expected)
        history_rows={};history_names=None;paths={}
        for h,item in w['histories'].items():
            equal('history',prefix+':'+h+':all_steps',[s['step']for s in item['steps']],list(range(1,9)))
            equal('history',prefix+':'+h+':audit_points',[a['step']for a in item['anchors']],list(POINTS))
            previous=None;history_rows[h]={};paths[h]=[]
            for s in item['steps']:
                t=s['step'];label=prefix+':'+h+':step'+str(t)
                equal('history',label+':policy',s['method'],h)
                selected=protocol['schedules'][str(seed)]['history_batches'][t-1]
                equal('batch',label+':indices',s['batch_indices'],selected)
                equal('batch',label+':tokens',s['batch_tokens_sha256'],token_hash([data['train'][i]for i in selected]))
                rows=checker(label,s['checker_receipts'],t,'history',history_names)
                if history_names is None:history_names=[r['name']for r in rows]
                equal('chain',label+':before',full_state(rows,'input'),s['state_sha256_before'])
                equal('chain',label+':after',full_state(rows,'output'),s['state_sha256_after'])
                if previous is not None:equal('chain',label+':previous_after',previous,s['state_sha256_before'])
                else:
                    first_states.append(s['state_sha256_before'])
                    for row in rows:
                        for field in ('exp_avg','exp_avg_sq'):equal('chain',label+':fresh_'+field+':'+row['name'],row['input_sha256'][field],zero_hash(row['shape']))
                previous=s['state_sha256_after'];history_rows[h][t]=rows
                check('history',label+':finite_actual_delta',math.isfinite(s['actual_native_delta_l2'])and s['actual_native_delta_l2']>=0)
                paths[h].append(s['actual_native_delta_l2'])
                equal('history',label+':grad_cleared',s['history_gradients_cleared'],True)
                gradient(label,s['gradient_diagnostic'],h)
            equal('chain',prefix+':'+h+':final_full_state',previous,item['final_full_state_sha256'])
            near('history',prefix+':'+h+':path_length',item['actual_update_path_length'],sum(paths[h]))
            check('history',prefix+':'+h+':theta_changed',item['final_parameter_sha256']!=w['initial_parameter_sha256'])
            for anchor in item['anchors']:
                t=anchor['step'];label=prefix+':'+h+':audit'+str(t);source=history_rows[h][t]
                equal('anchor',label+':history',anchor['history'],h)
                equal('anchor',label+':source_fullstate',anchor['source_full_state_sha256'],full_state(source,'output'))
                equal('anchor',label+':source_moments',anchor['frozen_optimizer_state_sha256'],moment_state(source,'output'))
                for key in ('source_state_buffers_rng_unchanged','audit_gradients_cleared'):equal('anchor',label+':'+key,anchor[key],True)
                selected=config['audit_batches'][str(t)]
                equal('batch',label+':indices',anchor['batch_indices'],selected)
                equal('batch',label+':tokens',anchor['batch_tokens_sha256'],token_hash([data['audit'][i]for i in selected]))
                policies=anchor['policies'];equal('anchor',label+':policies',[r['method']for r in policies],list(METHODS))
                equal('anchor',label+':gradient_methods',[g['method']for g in anchor['gradients']],list(METHODS))
                equal('anchor',label+':same_forward',len({(g['logits_sha256'],g['forward_loss'])for g in anchor['gradients']}),1)
                dense_rows=policies[0]['update_comparison']['per_parameter']
                for g,r in zip(anchor['gradients'],policies):
                    plabel=label+':'+r['method'];gradient(plabel,g,r['method'])
                    rows=checker(plabel,r['checker_receipts'],t+1,'clone',history_names)
                    equal('anchor',plabel+':same_fullstate',full_state(rows,'input'),anchor['source_full_state_sha256'])
                    equal('anchor',plabel+':same_initial_fullstate',r['initial_full_state_sha256'],anchor['source_full_state_sha256'])
                    equal('anchor',plabel+':same_initial_moments',r['initial_state_sha256'],anchor['frozen_optimizer_state_sha256'])
                    equal('anchor',plabel+':clone_moments',r['initial_optimizer_clone_sha256'],anchor['frozen_optimizer_state_sha256'])
                    for key in ('initial_parameter_sha256','initial_parameter_clone_sha256'):equal('anchor',plabel+':'+key,r[key],named_hash(source,'output','parameter'))
                    equal('anchor',plabel+':clone_gradient',r['initial_gradient_clone_sha256'],named_hash(rows,'input','gradient'))
                    equal('anchor',plabel+':input_steps',r['input_steps'],{n:t for n in history_names})
                    equal('anchor',plabel+':output_steps',r['optimizer_steps'],{n:t+1 for n in history_names})
                    equal('anchor',plabel+':one_native_step',r['native_optimizer_steps'],1)
                    for key in ('sources_unchanged','clone_storages_disjoint','numpy_all_parameter_and_moment_checks_passed'):equal('anchor',plabel+':'+key,r[key],True)
                    comparison(plabel,r['update_comparison'],history_names)
                    for stat,native,dense in zip(r['update_comparison']['per_parameter'],rows,dense_rows):
                        for key,field in [('parameter_sha256_before','parameter'),('gradient_sha256','gradient')]:equal('receipt',plabel+':'+stat['name']+':'+key,stat[key],native['input_sha256'][field])
                        equal('receipt',plabel+':'+stat['name']+':after',stat['parameter_sha256_after'],native['output_sha256']['parameter'])
                        for field in ('exp_avg','exp_avg_sq'):equal('receipt',plabel+':'+stat['name']+':'+field,stat[field+'_sha256'],native['output_sha256'][field])
                        equal('receipt',plabel+':'+stat['name']+':reference_update',stat['reference_update_sha256'],dense['candidate_update_sha256'])
                        for key in ('numpy_reference_sha256','numpy_reference_parity'):equal('receipt',plabel+':'+stat['name']+':'+key,stat[key],native[key])
                calculated=gate(policies);equal('gate',label+':joint',anchor['gate'],calculated)
                all_gates.append({'seed':seed,'history':h,'step':t,**calculated})
                b,treatment=[r['update_comparison']['aggregate']for r in policies[1:]]
                exact.append({'seed':seed,'history':h,'step':t,'norm_only_relative_l2':b['relative_l2'],
                    'treatment_relative_l2':treatment['relative_l2'],'norm_only_cosine':b['cosine_similarity'],
                    'treatment_cosine':treatment['cosine_similarity'],**calculated})
        equal('drift',prefix+':points',[d['step']for d in w['trajectory_drift']],list(POINTS))
        for d in w['trajectory_drift']:
            t=d['step'];label=prefix+':drift'+str(t)
            equal('drift',label+':descriptive',d['descriptive_only'],True)
            equal('drift',label+':counters_equal',d['native_counters_equal_checkpoint'],True)
            check('drift',label+':no_gate','gate'not in d and'passed'not in d)
            for field in ('parameter','exp_avg','exp_avg_sq'):comparison(label+':'+field,d[field],history_names,True)
            diff=d['parameter']['aggregate']['difference_l2'];norms=d['normalizations']
            equal('drift',label+':denominator_names',set(norms),{'dense_cumulative_displacement','dense_update_path_length'})
            path=sum(paths['dense'][:t]);displacement=norms['dense_cumulative_displacement']['denominator_l2']
            near('drift',label+':path_length_sum',norms['dense_update_path_length']['denominator_l2'],path)
            check('drift',label+':displacement_triangle',math.isfinite(displacement)and 0<=displacement<=path+8*math.ulp(max(path,1e-300)))
            check('drift',label+':paired_path_triangle',diff<=path+sum(paths[HISTORIES[1]][:t])+8*math.ulp(max(path,1e-300)))
            for key,value in norms.items():
                denom=value['denominator_l2'];check('drift',label+':'+key+':nonnegative',math.isfinite(denom)and denom>=0)
                if denom:
                    near('drift',label+':'+key+':ratio',value['parameter_drift_ratio'],diff/denom)
                    equal('drift',label+':'+key+':defined',value['undefined_reason'],None)
                else:
                    equal('drift',label+':'+key+':undefined_ratio',value['parameter_drift_ratio'],None)
                    equal('drift',label+':'+key+':undefined_reason',value['undefined_reason'],'zero '+key)
            drift_summary.append({'seed':seed,'step':t,'theta_difference_l2':diff,'theta_relative_l2':d['parameter']['aggregate']['relative_l2'],
                'm_difference_l2':d['exp_avg']['aggregate']['difference_l2'],'v_difference_l2':d['exp_avg_sq']['aggregate']['difference_l2'],
                'normalizations':norms})
    equal('chain','all_fresh_histories_identical',len(set(first_states)),1)
    equal('worker','all_pretrained_parameter_hashes',len({w['initial_parameter_sha256']for w in workers}),1)
    equal('counts','native_steps',dict(native_steps),{'history':48,'clone':36})
    equal('counts','native_parameter_checks',dict(native_parameter_checks),{'history':3648,'clone':2736})
    equal('counts','anchors',len(all_gates),12)
    totals={k:sum(w['counts'][k]for w in workers)for k in ('history_backwards','probe_backwards','native_history_steps','native_clone_steps')}
    equal('counts','actual_declared',{'workers':len(workers),**totals},config['expected_counts'])
    summary={'counts':{'workers':len(workers),**totals},'anchor_gates':all_gates,
             'primary_gate_passed_all_anchors':all(g['passed']for g in all_gates),'trajectory_drift_has_no_pass_threshold':True}
    reconstructed={'protocol_sha256':sha(protocol_path),'config_sha256':protocol['config_sha256'],'implementation_freeze_sha256':sha(freeze_path),
        'data_sha256':sha(data_path),'manifest_sha256':sha(manifest_path),'workers':[stable_worker(w)for w in workers],**summary}
    equal('report','complete_stable_reconstruction',stable,reconstructed)
    receipt={'schema_version':1,'audited_at':dt.datetime.now(dt.timezone.utc).isoformat(),'completed':True,'all_checks_passed':True,
        'checks_count':sum(checks.values()),'checks_by_category':dict(checks),'native_steps_checked':dict(native_steps),
        'native_parameter_steps_checked':dict(native_parameter_checks),'protocol_sha256':sha(protocol_path),'implementation_sha256':sha(freeze_path),
        'report_file_sha256':sha(report_path),'report_stable_sha256':report['stable_result_sha256'],'report_observation_sha256':report['observation_sha256'],
        'worker_file_receipts':raw_worker_receipts,'actual_exact_gate_data':exact,'descriptive_drift_summary':drift_summary,
        'classification':'valid_completed_scientific_gate_pass'if summary['primary_gate_passed_all_anchors']else'valid_completed_scientific_gate_failure',
        'execution_boundary':{'standard_library_only':True,'model_import_or_execution':False,'tracked_or_frozen_files_modified':False},
        'limitations':['Hashes,chronology,receipt chains,per-parameter sufficient-statistic algebra and gate/summary reconstruction were independently checked.',
            'Raw theta/gradient/m/v arrays are not published. Native-vs-NumPy interval receipts and storage/RNG invariants are reviewed-runtime assertions,not independently recomputed here.',
            'Drift sufficient-statistic algebra/aggregation and normalized ratios are verified. Dense path length is independently summed from step receipts. Raw arrays are needed to independently recompute each native delta norm or dense cumulative-displacement denominator and to relink drift norms to actual state values.',
            'No quality/convergence/efficiency/GPU/causal-state interpretation.']}
    receipt['audit_payload_sha256']=digest(receipt)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(canonical({k:receipt[k]for k in ('checks_count','classification','report_file_sha256','report_stable_sha256','audit_payload_sha256','actual_exact_gate_data','descriptive_drift_summary')}))

    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result',type=Path,default=ROOT/'results/activation-history',
        help='Result directory containing report.json and workers/ (default: repository results/activation-history).')
    parser.add_argument('--output',type=Path,required=True,
        help='New JSON receipt path; existing files are never overwritten.')
    args=parser.parse_args(argv)
    return audit(args.result,args.output)


if __name__=='__main__':
    main()
