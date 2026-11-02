"""Exercise the real preservation context before any model or optimizer work."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from experiments import native_training_cost as prior
from experiments import native_training_cost_scopes_v4 as current
from scripts import run_native_training_cost_scopes_v4 as launcher


class BeforeBatch(Exception):
    pass


class FakeModule:
    def __init__(self, name, events, explicit):
        self.name, self.events = name, events
        if explicit:
            self.forward = self.forbidden_forward

    def __setattr__(self, name, value):
        if name == 'forward':
            self.events.append(('set', self.name))
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        if name == 'forward':
            self.events.append(('del', self.name))
        object.__delattr__(self, name)

    def forbidden_forward(self, *args, **kwargs):
        raise AssertionError('A forward must not execute in this pure control')

    forward = forbidden_forward


class PreservationScopeBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.loaded_before = set(sys.modules)
        self.events = []
        self.norms = [(f'norm{i}', FakeModule(f'norm{i}', self.events, i % 2 == 0))
                      for i in range(13)]
        self.attentions = [(f'attention{i}', FakeModule(f'attention{i}', self.events, i % 2 == 0))
                           for i in range(6)]
        self.pairs = self.norms + self.attentions
        self.originals = [module.__dict__.copy() for _, module in self.pairs]
        self.forward_before = [module.forward for _, module in self.pairs]
        self.events.clear()
        self.getitem_calls = []
        self.optimizer = mock.Mock()
        self.model = mock.Mock()
        self.model.parameters.return_value = []

    def tearDown(self):
        self.assertEqual([module.__dict__ for _, module in self.pairs], self.originals)
        self.optimizer.zero_grad.assert_not_called()
        self.optimizer.step.assert_not_called()
        self.assertFalse({'torch', 'transformers', 'numpy'} & (set(sys.modules) - self.loaded_before))

    def tokens(self):
        owner = self

        class Tokens:
            def __getitem__(self, index):
                owner.getitem_calls.append(index)
                owner.assertTrue(all(module.forward != before for (_, module), before
                                     in zip(owner.pairs, owner.forward_before)))
                raise BeforeBatch('All19forwards wrapped; stop before batch/forward/backward/update')

        return Tokens()

    def invoke(self, study):
        # Keep the actual CostCodec constructor and preserve_scopes context.
        # Empty fake parameters avoid tensor/storage work. The first batch read
        # stops execution after all wrappers are installed and tests restoration.
        with mock.patch.object(current.cost, 'require_torch', return_value=object()), \
             mock.patch.object(current.cost, 'preservation_modules', return_value=(self.norms, self.attentions)), \
             mock.patch.object(current.cost, 'forward_loss') as forward:
            try:
                study.training_loop(self.model, self.optimizer, self.tokens(), [[0, 1]], study.jobs()[1])
            finally:
                forward.assert_not_called()

    def test_frozen_prior_rejects_nested_groups_before_batch_read(self):
        with self.assertRaisesRegex(ValueError, 'too many values to unpack'):
            self.invoke(prior)
        self.assertEqual(self.getitem_calls, [])
        self.assertEqual(self.events, [])

    def test_versioned_caller_wraps_all19_in_order_and_restores_on_batch_sentinel(self):
        with self.assertRaises(BeforeBatch):
            self.invoke(current)
        self.assertEqual(self.getitem_calls, [[0, 1]])
        self.assertEqual(self.events[:19], [('set', name) for name, _ in self.pairs])
        self.assertEqual([name for _, name in self.events[19:]],
                         [name for name, _ in reversed(self.pairs)])


class VersionedLauncherBoundaryTest(unittest.TestCase):
    def test_actual_parser_binds_versioned_runner_and_normalizes_paths(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            protocol, freeze, output, plan = [folder / part for part in ('protocol.json', 'freeze.json', 'out', 'plan.json')]
            protocol.write_text('{}', encoding='utf-8')
            freeze.write_text(json.dumps({'entrypoint_sha256': hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest()}), encoding='utf-8')
            plan.write_text('{"control": "saved-only"}', encoding='utf-8')
            with mock.patch.object(current, 'run', return_value=False) as run:
                self.assertFalse(launcher.main(['--protocol', str(protocol), '--freeze', str(freeze),
                                                '--output', str(output), '--plan', str(plan)]))
            self.assertEqual(run.call_args.args,
                             (protocol.resolve(), freeze.resolve(), output.resolve(), {'control': 'saved-only'}))


if __name__ == '__main__':
    unittest.main()
