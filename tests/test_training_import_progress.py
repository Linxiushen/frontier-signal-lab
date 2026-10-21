"""Guarded mocks and archived receipts only; no ML/native/process execution."""
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import training_import_progress as p
from scripts import audit_training_ledger_v2 as audit

ROOT=Path(__file__).resolve().parents[1]
NONCE="a"*64


class ImportControls(unittest.TestCase):
    def setUp(self):
        guard=mock.patch.dict(os.environ,{})
        guard.start();self.addCleanup(guard.stop)

    def run_import(self, failure=None):
        events=[]
        site=SimpleNamespace(ENABLE_USER_SITE=True)
        def site_main():
            if failure=="site":raise RuntimeError("site failure")
        site.main=site_main
        def imported(name):
            if failure==name:raise RuntimeError(name+" failure")
            version=p.duty.prior.CONFIG[name+"_version"]
            return SimpleNamespace(__version__="wrong" if failure=="version" else version)
        progress=SimpleNamespace(emit=events.append)
        with mock.patch.dict(sys.modules,{"site":site}),mock.patch.object(p.importlib,"import_module",side_effect=imported):
            if failure:
                with self.assertRaises((RuntimeError,p.duty.obs.ObserverError)):
                    p.import_packages(progress)
            else:
                p.import_packages(progress)
        self.assertFalse(site.ENABLE_USER_SITE)
        return events

    def test_exact_import_sequence_and_versions(self):
        self.assertEqual(self.run_import(),list(p.STEPS))
        self.assertTrue(all(os.environ[k]==v for k,v in p.duty.prior.OFFLINE_ENV.items()))

    def test_failure_keeps_only_completed_prefix_without_retry(self):
        for failure,length in [("site",1),("torch",3),("transformers",5),("version",6)]:
            with self.subTest(failure=failure):
                self.assertEqual(self.run_import(failure),list(p.STEPS[:length]))

    def test_actual_worker_ast_diff_is_only_the_import_call(self):
        old=ast.parse((ROOT/'experiments/observer_duty_v2.py').read_text(encoding='utf8'))
        new=ast.parse((ROOT/'experiments/training_ledger_worker_v2.py').read_text(encoding='utf8'))
        before=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name=='worker')
        after=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name=='worker')
        class Restore(ast.NodeTransformer):
            def visit_Call(self,node):
                if isinstance(node.func,ast.Attribute)and isinstance(node.func.value,ast.Name)and node.func.value.id=='progress'and node.func.attr=='import_packages':
                    return ast.parse('prior.import_packages()',mode='eval').body
                return self.generic_visit(node)
        self.assertEqual(ast.dump(before),ast.dump(Restore().visit(after)))

    def test_atomic_bounded_rows_and_order_identity_rejections(self):
        identity={"pid":os.getpid(),"creation_filetime":123}
        guard=SimpleNamespace(receipt=lambda:{"phase":"import"})
        with tempfile.TemporaryDirectory()as directory:
            writer=p.ImportProgress(directory,NONCE,identity,guard)
            with self.assertRaises(p.duty.obs.ObserverError):writer.emit("torch-start")
            for step in p.STEPS:writer.emit(step)
            rows=p.read_prefix(directory,NONCE,identity,0,float('inf'),complete=True)
            self.assertEqual([r['step']for r in rows],list(p.STEPS))
            self.assertFalse(list(Path(directory).glob('*.pending')))
            with self.assertRaises(p.duty.obs.ObserverError):writer.emit("versions-verified")
        for wrong in ['identity','size']:
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory()as directory:
                ident=dict(identity,pid=identity['pid']+1)if wrong=='identity'else identity
                bad=SimpleNamespace(receipt=lambda:{"value":"x"*8192})if wrong=='size'else guard
                writer=p.ImportProgress(directory,NONCE,ident,bad)
                with self.assertRaises(p.duty.obs.ObserverError):writer.emit('site-start')
                self.assertEqual(list(Path(directory).iterdir()),[])

    def test_incomplete_prefix_remains_failure_and_bad_custody_rejects(self):
        ident={"pid":os.getpid(),"creation_filetime":123}
        for mutation in ['incomplete','nonce','pid','creation','clock','step','gap','oversize','pending']:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory()as directory:
                writer=p.ImportProgress(directory,NONCE,ident,SimpleNamespace(receipt=lambda:{}))
                for step in p.STEPS[:1 if mutation=='incomplete'else 7]:writer.emit(step)
                file=Path(directory)/'import-progress-00.json'
                row=json.loads(file.read_bytes())
                for name,key,value in [('nonce','nonce','b'*64),('pid','pid',1),('creation','creation_filetime',999),
                    ('clock','emitted_perf_counter',-1),('step','step','torch-start')]:
                    if mutation==name:row[key]=value
                file.write_text(json.dumps(row),encoding='utf8')
                if mutation=='gap':file.rename(file.with_name('import-progress-09.json'))
                if mutation=='oversize':file.write_bytes(b' '*8193)
                if mutation=='pending':(Path(directory)/'import-progress-07.json.pending').write_bytes(b'x')
                with self.assertRaises(p.duty.obs.ObserverError):
                    p.read_prefix(directory,NONCE,ident,0,float('inf'),complete=True)


class IndependentProgressAudit(unittest.TestCase):
    def archive(self):
        r=json.loads((ROOT/'results/observer-duty-v2/report.json').read_bytes())
        c=copy.deepcopy(r['cases'][1]);f=json.loads((ROOT/'fixtures/observer-duty-v2/implementation.json').read_bytes())
        wid=c['worker_identity']['self_receipt'];stage=c['stages']
        low=stage['preimport']['stage_ready_perf_counter'];upper=stage['postimport']['import_completed_perf_counter']
        final=copy.deepcopy(stage['postimport']['provider_guard']);final['phase']='import'
        probe=final['diagnostic_events'][0]['perf_counter']
        empty=copy.deepcopy(stage['preimport']['provider_guard']);empty['phase']='import'
        rows=[]
        for i,step in enumerate(p.STEPS):
            stamp=low+(probe-low)*(i+1)/8 if i<6 else probe+(upper-probe)/2
            rows.append({'nonce':c['nonce'],'role':'worker','pid':wid['pid'],'creation_filetime':wid['creation_filetime'],
                'seq':i,'step':step,'emitted_perf_counter':stamp,'provider_guard':copy.deepcopy(empty if i<6 else final)})
        c['import_progress']=rows
        return c,f,rows

    def test_independent_saved_byte_schema_and_mutations(self):
        for mutation in [None,'nonce','pid','clock','provider','prefix','source','missing','tail']:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory()as tmp:
                c,f,rows=self.archive()
                if mutation=='nonce':rows[0]['nonce']='c'*64
                if mutation=='pid':rows[0]['pid']+=1
                if mutation=='clock':rows[0]['emitted_perf_counter']=rows[-1]['emitted_perf_counter']+1
                if mutation=='provider':rows[-1]['provider_guard']['allowed_local_probe_budget']=2
                if mutation=='prefix':rows[0]['provider_guard']=copy.deepcopy(rows[-1]['provider_guard'])
                if mutation=='source':rows[-1]['provider_guard']['provider_source']['sha256']='0'*64
                for i,row in enumerate(rows[:6 if mutation=='missing'else 7]):
                    (Path(tmp)/f'import-progress-{i:02d}.json').write_text(json.dumps(row),encoding='utf8')
                if mutation=='tail':(Path(tmp)/'import-progress-07.json.pending').write_bytes(b'partial')
                if mutation:
                    with self.assertRaises(AssertionError):audit.audit_progress(c,Path(tmp),f)
                else:self.assertEqual(audit.audit_progress(c,Path(tmp),f)['rows'],7)


if __name__=='__main__':unittest.main()
