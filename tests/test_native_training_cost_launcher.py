"""Post-outcome entrypoint regressions; no native process or model execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_native_training_cost as entry


class NativeCostLauncherTest(unittest.TestCase):
    def test_real_entrypoint_resolves_every_cli_path_before_run(self):
        # Use actual relative CLI args against the real parser and boundary.
        # Only the expensive native/model runner is replaced.
        with tempfile.TemporaryDirectory(dir=Path.cwd())as tmp:
            root=Path(tmp);freeze=root/'freeze.json';plan=root/'plan.json'
            freeze.write_text(json.dumps({'entrypoint_sha256':entry.study.cost.file_hash(Path(entry.__file__))}),encoding='utf8')
            plan.write_text('{"prepared":true}',encoding='utf8')
            rel=root.relative_to(Path.cwd())
            args=['--protocol',str(rel/'protocol.json'),'--freeze',str(rel/'freeze.json'),
                '--output',str(rel/'output'),'--plan',str(rel/'plan.json')]
            with patch.object(entry.study,'run',return_value=True)as run:
                self.assertTrue(entry.main(args))
            self.assertEqual(run.call_args.args,(root/'protocol.json',freeze,root/'output',{'prepared':True}))
            self.assertTrue(all(p.is_absolute()for p in run.call_args.args[:3]))

    def test_old_or_changed_freeze_cannot_authorize_corrected_launch(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);freeze=root/'freeze.json'
            for obj in [{},{'entrypoint_sha256':'0'*64}]:
                freeze.write_text(json.dumps(obj),encoding='utf8')
                with patch.object(entry.study,'run')as run:
                    with self.assertRaises(ValueError):entry.main(['--protocol',str(root/'p.json'),
                        '--freeze',str(freeze),'--output',str(root/'out'),'--plan',str(root/'plan.json')])
                    run.assert_not_called()


if __name__=='__main__':unittest.main()
