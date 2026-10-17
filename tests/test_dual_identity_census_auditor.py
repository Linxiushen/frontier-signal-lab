"""Synthetic-only receipt mutations. No observer/OS/ML imports or process starts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from scripts import audit_dual_identity_census as a

def fixture():
    source={p:'1'*64 for p in a.SOURCE_PATHS};deps={p:'2'*64 for p in a.DEPENDENCY_PATHS}
    reviews={p:'3'*64 for p in a.REVIEW_PATHS}
    exes=dict(zip(('launcher','base_python','native'),('a'*64,'b'*64,'c'*64)));paths={k:str(i)*64 for i,k in enumerate(exes,4)}
    protocol={'schema_version':1,'experiment_id':'windows-dual-identity-census-v1','config':dict(a.CONFIG),'source_paths':list(a.SOURCE_PATHS),'frozen_dependency_paths':list(a.DEPENDENCY_PATHS),'cases_in_order':[{'id':n,'injected':i}for n,i in a.CASES],'training_permitted':False,'self_executable_roles':dict(a.SELF_ROLES),'retained_os_image_roles':dict(a.OS_ROLES),'predeclared_at':'2026-01-01T00:00:00Z'}
    protocol['review_tool_paths']=list(a.REVIEW_PATHS)
    freeze={'protocol_sha256':'d'*64,'new_source_files_sha256':source,'frozen_dependency_files_sha256':deps,'review_tools_sha256':dict(reviews),'executables_sha256':exes,'executable_path_sha256':dict(paths),'frozen_at':'2026-01-01T00:01:00Z'}
    report={'schema_version':1,'experiment_id':protocol['experiment_id'],'passed':True,'os_name':'nt','no_fallback':True,'self_executable_roles':dict(a.SELF_ROLES),'retained_os_image_roles':dict(a.OS_ROLES),'training_permitted':False,'model_loads':0,'optimizer_steps':0,'protocol_sha256':'d'*64,'implementation_sha256':'e'*64,'source_sha256':source,'dependencies_sha256':deps,'executables_sha256':exes,'executable_path_sha256':paths,'protocol_predeclared_at':protocol['predeclared_at'],'implementation_frozen_at':freeze['frozen_at'],'started_at':'2026-01-01T00:02:00Z','completed_at':'2026-01-01T00:02:12Z','started_perf_counter':100.,'completed_perf_counter':112.,'wall_seconds':12.,'cases':[]}
    for index,(name,injected) in enumerate(a.CASES):
        start=100.+6*index;pid=100+100*index;nonce=str(index*2+1)*64;helper_nonce=str(index*2+2)*64
        identities={pid:1000+index*100,pid+1:1001+index*100,pid+2:1003+index*100,pid+3:1002+index*100,pid+4:1004+index*100}
        parents={pid:999,pid+1:pid,pid+2:pid+1,pid+3:pid+1,pid+4:pid+1}
        def ident(p):return {'pid':p,'creation_filetime':identities[p],'parent_pid':parents[p],'job_member':True}
        def message(p,n,role):return {'pid':p,'nonce':n,'role':role}
        def ready(p,n,role,t):return {**ident(p),**message(p,n,role),'perf_counter':t,'self_executable':{'source':'sys.executable','basename':'python.exe','sha256':exes[a.SELF_ROLES[role]],'normalized_path_sha256':paths[a.SELF_ROLES[role]]}}
        def node(p,role=None):
            match=role or ('base_python'if p==pid+4 else None)
            image={'basename':'cmd.exe'if role=='native'else 'python.exe'if match else 'console.exe','sha256':exes[match]if match else '8'*64,'normalized_path_sha256':paths[match]if match else '9'*64,'exact_path_matches':[match]if match else [],'path_classification':'exact_executable'if match else 'system32','queried_from_retained_handle':True,'retained_identity_stable':True}
            return {**ident(p),'alive':True,'policy_role':role or 'unapproved','approved_known':bool(role),'image':image}
        flags={'training_permitted':False,'model_loads':0,'optimizer_steps':0,'torch_imported':False,'transformers_imported':False}
        case={'id':name,'injected':injected,'passed':True,'nonce':nonce,'helper_nonce':helper_nonce,'started_at':f'2026-01-01T00:02:{index*6:02d}Z','completed_at':f'2026-01-01T00:02:{index*6+5:02d}Z','started_perf_counter':start,'completed_perf_counter':start+5,'wall_seconds':5.,'training_permitted':False,'model_loads':0,'optimizer_steps':0,
            'launcher':{'pid':pid,'creation_filetime':identities[pid],'assigned_while_suspended':True,'job_handle_inherited':False},'worker_identity':{'self_executable_expected_role':'launcher','retained_os_image_expected_role':'base_python','self_receipt':ready(pid+1,nonce,'worker',start+.1),'verified_ancestry':[ident(pid+1),ident(pid)]},'worker_census_state':{**message(pid+1,nonce,'worker'),**flags},'censuses':[]}
        launch={**message(pid+1,nonce,'worker'),'native_pid':pid+2,'command_arguments':list(a.NATIVE_ARGUMENTS),'close_fds':True,'stdin_anonymous_pipe':True,'shell':False,'creationflags':0x08000000,'stdout_devnull':True,'stderr_devnull':True}
        case['native_descendant']={'launch_receipt':launch,'os_identity':{k:v for k,v in ident(pid+2).items()if k!='job_member'},'os_image':{'basename':'cmd.exe','sha256':exes['native'],'matches_frozen':True},'job_member':True,'no_native_self_report':True}
        for j,label in enumerate(['before_native','after_native']+(['after_helper']if injected else [])):
            nodes=[node(pid,'launcher'),node(pid+1,'base_python'),node(pid+3)]
            if j:nodes.append(node(pid+2,'native'))
            if j==2:nodes.append(node(pid+4))
            begin=start+.2+j*.25;end=begin+.05;pids=sorted(n['pid']for n in nodes)
            case['censuses'].append({'label':label,'training_permitted':False,'started_perf_counter':begin,'completed_perf_counter':end,'wall_seconds':end-begin,'processes':nodes,'observed_pids':pids,'snapshot_observed_count':len(nodes),'job_count_before':len(nodes),'job_count_after':len(nodes),'job_count_matches_before':True,'job_count_matches_after':True,'all_known_present':True,'census_complete':True,'errors':[],'truncated':False,'query_budget_exceeded':False,'unapproved_pids':sorted(n['pid']for n in nodes if not n['approved_known'])})
        case['before_native_unapproved_pids']=[pid+3]
        live_pids=[pid+1,pid+2]
        if injected:
            case['injected_helper']={'self_executable_expected_role':'base_python','retained_os_image_expected_role':'base_python','self_receipt':ready(pid+4,helper_nonce,'helper',start+.6),'verified_ancestry':[ident(pid+4),ident(pid+1)],'launch_receipt':{**message(pid+1,nonce,'worker'),'helper_launcher_pid':pid+4,'base_executable_sha256':exes['base_python'],'shell':False,'close_fds':True,'creationflags':0x08000000}}
            case['rejection']={'helper_pid':pid+4,'training_permitted':False,'ML_release_absent':True};case.update(termination_started_perf_counter=start+1,termination_returned_perf_counter=start+1.01,outcome='identified_helper_rejected_no_training');live_pids.append(pid+4)
        else:case['completion']={**message(pid+1,nonce,'worker'),**flags,'native_exit_code':0,'native_released_nonempty_line':True};case['outcome']='graceful_census_no_training'
        case['pretermination_live_members'if injected else 'prefinish_live_members']=[{**ident(p),'alive':True,'verified_perf_counter':start+.9}for p in live_pids]
        all_pids=[pid,pid+1,pid+2,pid+3]+([pid+4]if injected else [])
        case['cleanup']={'all_retained_handles_exited':True,'job_active_count':0,'started_perf_counter':start+1.02,'completed_perf_counter':start+1.1,'wall_seconds':.08,'timeout_seconds':3.9,'exit_codes':[{'pid':p,'creation_filetime':identities[p],'exit_code':57347 if injected and p in (pid,pid+1,pid+4)else 77 if p==pid+3 else 0}for p in all_pids]}
        report['cases'].append(case)
    # Keep each purported independent hash inventory independent under mutation.
    report['source_sha256']=dict(source);report['dependencies_sha256']=dict(deps);report['executables_sha256']=dict(exes)
    report['review_tools_sha256']=dict(reviews)
    return report,protocol,freeze,{'protocol_sha256':'d'*64,'freeze_sha256':'e'*64,'actual_source_sha256':dict(source),'actual_dependency_sha256':dict(deps),'actual_review_tools_sha256':dict(reviews)}

class DualIdentityAuditorTests(unittest.TestCase):
    def setUp(self): self.report,self.protocol,self.freeze,self.kw=fixture()
    def run_audit(self): return a.audit(self.report,self.protocol,self.freeze,**self.kw)
    def reject(self,mutate):
        pristine=copy.deepcopy((self.report,self.protocol,self.freeze,self.kw));mutate();result=self.run_audit()
        self.assertFalse(result['passed'],result);self.assertTrue(result['failures']);self.report,self.protocol,self.freeze,self.kw=pristine
    def test_complete_synthetic_unknown_images_are_not_training_approval(self):
        result=self.run_audit();self.assertTrue(result['passed'],result['failures']);self.assertFalse(result['training_permitted']);self.assertEqual(len(result['case_summaries']),2)
        self.assertEqual(self.report['cases'][1]['cleanup']['exit_codes'][2]['exit_code'],0) # cmd may receive EOF first
        worker=self.report['cases'][0]['worker_identity']['self_receipt'];os_node=self.report['cases'][0]['censuses'][0]['processes'][1]
        self.assertNotEqual(worker['self_executable']['sha256'],os_node['image']['sha256']) # venv split regression
    def test_equal_binary_hashes_do_not_collapse_independent_roles(self):
        self.freeze['executables_sha256']['launcher']=self.report['executables_sha256']['launcher']=self.freeze['executables_sha256']['base_python']
        for case in self.report['cases']:
            case['worker_identity']['self_receipt']['self_executable']['sha256']=self.freeze['executables_sha256']['launcher']
            for stage in case['censuses']:
                stage['processes'][0]['image']['sha256']=self.freeze['executables_sha256']['launcher']
        self.assertTrue(self.run_audit()['passed'])
    def test_independent_identity_contract_and_self_path(self):
        for mutate in (lambda:self.report['cases'][0]['worker_identity']['self_receipt']['self_executable'].update(sha256='b'*64,normalized_path_sha256='5'*64),lambda:self.report['cases'][0]['worker_identity']['self_receipt']['self_executable'].update(normalized_path_sha256='5'*64),lambda:self.report['cases'][1]['injected_helper']['self_receipt']['self_executable'].update(sha256='a'*64,normalized_path_sha256='4'*64),lambda:self.report['cases'][0]['worker_identity'].update(retained_os_image_expected_role='launcher'),lambda:self.protocol['self_executable_roles'].update(worker='base_python'),lambda:self.report['cases'][0]['worker_identity']['self_receipt']['self_executable'].update(source='OS-image'),lambda:self.report['cases'][0]['worker_identity']['self_receipt']['self_executable'].update(basename='unrelated.exe'),lambda:self.report['cases'][0]['worker_identity']['self_receipt'].update(runtime_executable_sha256='a'*64)):
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_optional_local_executable_rehash_inventory(self):
        self.kw['executable_sha256']=dict(self.freeze['executables_sha256']);self.assertTrue(self.run_audit()['passed'])
        self.reject(lambda:self.kw['executable_sha256'].update(base_python='0'*64))
    def test_hash_protocol_and_declaration_mutations(self):
        for mutate in (lambda:self.kw.update(protocol_sha256='0'*64),lambda:self.kw['actual_source_sha256'].update({a.SOURCE_PATHS[0]:'0'*64}),lambda:self.kw['actual_review_tools_sha256'].update({a.REVIEW_PATHS[0]:'0'*64}),lambda:self.report['executables_sha256'].update(native='0'*64),lambda:self.report['executable_path_sha256'].update(native='0'*64),lambda:self.freeze['executable_path_sha256'].update(launcher='0'*64),lambda:self.protocol['config'].update(maximum_descendants=99),lambda:self.freeze.update(frozen_at='2027-01-01T00:00:00Z')):
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_training_imports_and_hidden_failures(self):
        for mutate in (lambda:self.report.update(training_permitted=True),lambda:self.report['cases'][0]['worker_census_state'].update(torch_imported=True),lambda:self.report['cases'][0]['completion'].update(model_loads=1),lambda:self.report['cases'][1]['rejection'].update(ML_release_absent=False),lambda:self.report['cases'][1].update(error='failure'),lambda:self.report['cases'][0].update(passed=False),lambda:self.report['cases'][0].update(case_wall_budget_exceeded=True)):
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_helper_cannot_be_approved_by_identical_path_hash(self):
        def promote():
            row=self.report['cases'][1]['censuses'][-1];helper=next(n for n in row['processes']if n['pid']==204);helper.update(approved_known=True,policy_role='base_python');row['unapproved_pids'].remove(204)
        self.reject(promote);self.reject(lambda:self.report['cases'][1]['injected_helper']['self_receipt'].update(nonce='0'*64))
    def test_complete_tree_images_and_query_errors(self):
        row=self.report['cases'][0]['censuses'][1]
        for mutate in (lambda:row['processes'].pop(),lambda:row['processes'][2].update(parent_pid=9999),lambda:row['processes'][1]['image'].update(sha256=None),lambda:row['processes'][2]['image'].update(retained_identity_stable=False),lambda:row.update(job_count_after=99),lambda:row['errors'].append({'pid':103,'error':'hash failed'})):
            # Resolve row anew after each restored copy.
            self.report,self.protocol,self.freeze,self.kw=fixture();row=self.report['cases'][0]['censuses'][1]
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_identity_parent_creation_and_native_contract(self):
        for mutate in (lambda:self.report['cases'][0]['censuses'][1]['processes'][0].update(creation_filetime=9999),lambda:self.report['cases'][1]['injected_helper']['verified_ancestry'][0].update(parent_pid=999),lambda:self.report['cases'][0]['native_descendant']['launch_receipt'].update(shell=True),lambda:self.report['cases'][0]['censuses'][1]['processes'][1]['image'].update(normalized_path_sha256='0'*64),lambda:self.report['cases'][0]['censuses'][1]['processes'][-1].update(parent_pid=100),lambda:self.report['cases'][1]['censuses'][-1]['processes'][-1].update(parent_pid=200)):
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_known_controls_cannot_predate_creation_stage(self):
        def early(case_index,source_stage,target_stage,pid):
            case=self.report['cases'][case_index];row=case['censuses'][target_stage]
            node=copy.deepcopy(next(n for n in case['censuses'][source_stage]['processes']if n['pid']==pid));node.update(approved_known=False,policy_role='unapproved');row['processes'].append(node)
            row['observed_pids']=sorted(n['pid']for n in row['processes']);row['unapproved_pids']=sorted([*row['unapproved_pids'],pid])
            for field in ('snapshot_observed_count','job_count_before','job_count_after'):row[field]=len(row['processes'])
            if target_stage==0:case['before_native_unapproved_pids']=list(row['unapproved_pids'])
        for mutate in (lambda:early(0,1,0,102),lambda:early(1,2,0,204),lambda:early(1,2,1,204)):
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_clock_cleanup_and_exit_mutations(self):
        for mutate in (lambda:self.report['cases'][0]['censuses'][0].update(completed_perf_counter=float('nan')),lambda:self.report['cases'][0]['cleanup'].update(job_active_count=1),lambda:self.report['cases'][1]['cleanup']['exit_codes'].pop(),lambda:self.report['cases'][1]['cleanup']['exit_codes'][1].update(exit_code=0),lambda:self.report['cases'][1]['pretermination_live_members'][0].update(verified_perf_counter=108.),lambda:self.report['cases'][1]['injected_helper']['self_receipt'].update(perf_counter=108.),lambda:self.report.update(wall_seconds=99)):
            with self.subTest(mutate=mutate):self.reject(mutate)
    def test_actual_file_hashes_and_strict_JSON(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp)
            for name in (*a.SOURCE_PATHS,*a.DEPENDENCY_PATHS,*a.REVIEW_PATHS):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            self.freeze['new_source_files_sha256']={p:a.sha((root/p).read_bytes())for p in a.SOURCE_PATHS};self.freeze['frozen_dependency_files_sha256']={p:a.sha((root/p).read_bytes())for p in a.DEPENDENCY_PATHS}
            self.freeze['review_tools_sha256']={p:a.sha((root/p).read_bytes())for p in a.REVIEW_PATHS};self.report['review_tools_sha256']=dict(self.freeze['review_tools_sha256'])
            self.report['source_sha256']=self.freeze['new_source_files_sha256'];self.report['dependencies_sha256']=self.freeze['frozen_dependency_files_sha256']
            pp=root/'protocol.json';fp=root/'freeze.json';rp=root/'report.json';pp.write_text(json.dumps(self.protocol));self.freeze['protocol_sha256']=self.report['protocol_sha256']=a.sha(pp.read_bytes());fp.write_text(json.dumps(self.freeze));self.report['implementation_sha256']=a.sha(fp.read_bytes());rp.write_text(json.dumps(self.report))
            self.assertTrue(a.audit_files(rp,pp,fp,root=root)['passed']);(root/a.SOURCE_PATHS[0]).write_bytes(b'changed');self.assertFalse(a.audit_files(rp,pp,fp,root=root)['passed'])
            for content in ('{"a":1,"a":2}','{"a":NaN}'):
                rp.write_text(content)
                with self.assertRaises(ValueError):a.bounded(rp)

if __name__=='__main__':unittest.main()
