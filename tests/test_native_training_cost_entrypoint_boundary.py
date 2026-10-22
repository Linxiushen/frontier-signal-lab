"""Real CLI -> frozen runner path boundary, stopped before any native launch.

Local executable/model/resource checks use fixture pins or mocks. These are
portable invocation controls, not a native or training acceptance suite.
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_native_training_cost as entry


class BoundaryReached(Exception):
    pass


class NativeCostEntrypointBoundaryTest(unittest.TestCase):
    def prepared(self, root):
        s=entry.study
        exe=root/'runtime'/'python.exe';exe.parent.mkdir();exe.write_bytes(b'fixture executable')
        provider=root/'site'/'urllib3'/'util'/'connection.py'
        provider.parent.mkdir(parents=True);provider.write_bytes(b'fixture provider source')
        protocol=root/'protocol.json';freeze=root/'freeze.json';plan=root/'plan.json';output=root/'new output'
        p={'id':s.ID,'jobs':s.jobs(),'config':s.CONFIG,'ledger_limits':s.LIMITS,
           'predeclared_at':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()}
        pins={k:exe for k in ['launcher','base_python','native','conhost']}
        protocol.write_text(json.dumps(p),encoding='utf8')
        f={'entrypoint_sha256':s.cost.file_hash(Path(entry.__file__)),
           'source_sha256':{name:s.cost.file_hash(s.ROOT/name)for name in s.SOURCES},
           'protocol_sha256':s.cost.file_hash(protocol),'output_directory':output.relative_to(s.ROOT).as_posix(),
           'suites_permitted':1,'retries':0,'frozen_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),
           'executables_sha256':{k:s.cost.file_hash(v)for k,v in pins.items()},
           'executable_path_sha256':{k:s.dual.path_hash(v)for k,v in pins.items()},
           'provider_source_sha256':s.cost.file_hash(provider),'provider_source_path_sha256':s.dual.path_hash(provider),
           'python_runtime_files':{},'selected_runtime_files':{}}
        freeze.write_text(json.dumps(f),encoding='utf8')
        plan.write_text(json.dumps({'explicit_local_executable_paths':{k:str(v)for k,v in pins.items()},
            'model_dir':str(root/'model'),'fixture':str(s.ROOT/'fixtures/activation-cost'),'provider_source':str(provider)}),encoding='utf8')
        args=sum((['--'+name,str(value.relative_to(Path.cwd()))]for name,value in
            [('protocol',protocol),('freeze',freeze),('output',output),('plan',plan)]),[])
        return args,output,freeze,f

    def guards(self, freeze):
        s=entry.study;stack=ExitStack()
        stack.enter_context(patch.object(s.prior,'PROVIDER_SOURCE_SHA256',freeze['provider_source_sha256']))
        # Rebind only this runner's OS view; changing global os.name would
        # cause pathlib to construct WindowsPath on a Linux CI host.
        stack.enter_context(patch.object(s,'os',SimpleNamespace(name='nt')))
        stack.enter_context(patch.object(s.cost,'verify_model_assets'))
        stack.enter_context(patch.object(s.cost,'validate_fixture'))
        stack.enter_context(patch.object(s.cost,'free_memory_bytes',return_value=2**40))
        stack.enter_context(patch('shutil.disk_usage',return_value=type('Disk',(),{'free':2**40})()))
        native=stack.enter_context(patch.object(s.obs,'WindowsJob',side_effect=AssertionError('No native Job permitted in control')))
        case=stack.enter_context(patch.object(s,'run_case',side_effect=BoundaryReached))
        return stack,native,case

    def test_relative_exact_invocation_crosses_frozen_path_check_before_native(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd(),prefix='cost boundary ')as tmp:
            args,output,_,freeze=self.prepared(Path(tmp))
            stack,native,case=self.guards(freeze)
            with stack:
                with self.assertRaises(BoundaryReached):entry.main(args)
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()),[])
            self.assertEqual(case.call_count,1)
            self.assertEqual(case.call_args.args[-2],output)
            native.assert_not_called()

    def test_wrong_output_and_changed_source_are_refused_before_directory(self):
        for change in ['output','source']:
            with self.subTest(change=change),tempfile.TemporaryDirectory(dir=Path.cwd(),prefix='cost boundary ')as tmp:
                args,output,path,freeze=self.prepared(Path(tmp))
                bad=copy.deepcopy(freeze)
                if change=='output':bad['output_directory']+='-different'
                else:bad['source_sha256']['experiments/native_training_cost.py']='0'*64
                path.write_text(json.dumps(bad),encoding='utf8')
                stack,native,case=self.guards(freeze)
                with stack:
                    with self.assertRaisesRegex(ValueError,'Frozen execution contract differs'):entry.main(args)
                self.assertFalse(output.exists());case.assert_not_called();native.assert_not_called()


if __name__=='__main__':unittest.main()
