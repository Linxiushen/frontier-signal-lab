"""One frozen tiny CPU integration for caller-owned AdamW state; no downloads."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def tensor_hash(tensor):
    array = tensor.detach().contiguous().numpy()
    header = json.dumps({'dtype': str(array.dtype), 'shape': list(array.shape)}, sort_keys=True).encode()
    return hashlib.sha256(header + b'\0' + array.tobytes()).hexdigest()


def capture(model, optimizer, torch, np):
    values = {}
    for name, p in model.named_parameters():
        values[name] = {'parameter': tensor_hash(p), 'grad': tensor_hash(p.grad) if p.grad is not None else None,
                        'state': {key: tensor_hash(value) for key, value in optimizer.state.get(p, {}).items()}}
    return {'parameters': values, 'groups': [{k: v for k, v in g.items() if k != 'params'} for g in optimizer.param_groups],
            'python_rng': digest(random.getstate()), 'numpy_rng': digest([np.random.get_state()[0], np.random.get_state()[1].tolist(), *np.random.get_state()[2:]]),
            'torch_rng': tensor_hash(torch.get_rng_state())}


def trajectory_state(model, optimizer):
    return {name: {'parameter': p.detach().tolist(), 'state': {key: value.detach().tolist() for key, value in optimizer.state.get(p, {}).items()}}
            for name, p in model.named_parameters()}


def execute(protocol, record, output):
    import numpy as np
    import torch
    from savescope import SaveScopeError, audit
    from savescope.demo import as_report
    from savescope.report import write_report

    torch.set_num_threads(protocol['threads'])
    torch.manual_seed(protocol['seed'])
    np.random.seed(protocol['seed'])
    random.seed(protocol['seed'])
    options = dict(protocol['optimizer'])
    options['betas'] = tuple(options['betas'])

    class Block(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.extra = torch.nn.Parameter(torch.randn(protocol['outputs']))
            self.reserve = torch.nn.Parameter(torch.randn(protocol['outputs']))
            self.project = torch.nn.Linear(protocol['batch_shape'][-1], protocol['hidden'])
            self.norm = torch.nn.LayerNorm(protocol['hidden'])
            self.head = torch.nn.Linear(protocol['hidden'], protocol['outputs'])

        def forward(self, x, use_extra=False):
            result = self.head(self.norm(torch.tanh(self.project(x))))
            return result + self.extra if use_extra else result

    model = Block()
    optimizer = torch.optim.AdamW(model.parameters(), **options, foreach=False, fused=False)
    trajectory = [{'label': 'initial', 'values': trajectory_state(model, optimizer)}]
    for step in range(protocol['warmup_steps']):
        x = torch.randn(*protocol['batch_shape'])
        target = torch.randn(*protocol['batch_shape'][:-1], protocol['outputs'])
        optimizer.zero_grad(set_to_none=True)
        loss = (model(x, use_extra=step % 2 == 0) - target).square().mean()
        loss.backward()
        optimizer.step()
        record['warmup_updates_completed'] += 1
        trajectory.append({'label': 'warmup_' + str(step + 1), 'loss': float(loss.detach()), 'values': trajectory_state(model, optimizer)})
    optimizer.zero_grad(set_to_none=True)
    x = torch.randn(*protocol['batch_shape'])
    target = torch.randn(*protocol['batch_shape'][:-1], protocol['outputs'])
    before = capture(model, optimizer, torch, np)
    original_objects = [(p, p.grad, p.untyped_storage().data_ptr(), p._version) for p in model.parameters()]
    state_objects = [(value, value.untyped_storage().data_ptr(), value._version) for row in optimizer.state.values() for value in row.values()]
    reference = copy.deepcopy(model)
    reference_optimizer = torch.optim.AdamW(reference.parameters(), **options, foreach=False, fused=False)
    reference_optimizer.load_state_dict(copy.deepcopy(optimizer.state_dict()))
    original_values = {name: p.detach().clone() for name, p in reference.named_parameters()}
    direct_loss = (reference(x) - target).square().mean()
    direct_loss.backward()
    direct_gradients = {name: tensor_hash(p.grad) for name, p in reference.named_parameters() if p.grad is not None}
    direct_gradient_values = {name: p.grad.detach().tolist() for name, p in reference.named_parameters() if p.grad is not None}
    reference_optimizer.step()
    record['direct_reference_updates_completed'] = 1
    reference_after = trajectory_state(reference, reference_optimizer)
    result = audit(model, lambda m: m(x), lambda y: (y - target).square().mean(),
                   optimizer=optimizer, policies=protocol['policies'])
    record['stateful_arms_completed'] = len(result['arms'])
    dense = result['arms'][0]
    controls = {row['name']: row for row in dense['update']['independent_reference']['per_parameter']}
    updates = {row['name']: row for row in dense['update']['per_parameter']}
    gradients = {row['name']: row for row in dense['gradient']['per_parameter']}
    checks = {
        'all_policy_arms_valid': all(arm['numerically_valid'] for arm in result['arms']),
        'caller_values_groups_state_rng_unchanged': before == capture(model, optimizer, torch, np),
        'caller_parameter_grad_storage_versions_unchanged': all(p.grad is grad and p.untyped_storage().data_ptr() == ptr and p._version == version for p, grad, ptr, version in original_objects),
        'caller_optimizer_storage_versions_unchanged': all(value.untyped_storage().data_ptr() == ptr and value._version == version for value, ptr, version in state_objects),
        'unequal_input_steps': float(optimizer.state[model.extra]['step']) == 2 and float(optimizer.state[model.project.weight]['step']) == 4,
        'unused_initialized_state_retains_counter': controls['extra']['optimizer_step'] == 2,
        'unused_lazy_state_stays_absent': controls['reserve']['optimizer_step'] == 0 and model.reserve not in optimizer.state,
        'all_native_parameter_hashes_match': all(controls[name]['parameter_sha256_after'] == tensor_hash(p) for name, p in reference.named_parameters()),
        'all_native_update_hashes_match': all(updates[name]['sha256'] == tensor_hash(p.detach() - original_values[name]) for name, p in reference.named_parameters()),
        'all_used_native_gradient_hashes_match': all(gradients[name]['sha256'] == value for name, value in direct_gradients.items()),
    }
    fresh = audit(model, lambda m: m(x), lambda y: (y - target).square().mean(), policies=('dense',), optimizer_kwargs=options)
    record['fresh_control_arms_completed'] = 1
    checks['fresh_reset_produces_different_update'] = dense['update']['per_parameter'] != fresh['arms'][0]['update']['per_parameter']
    checks['caller_unchanged_after_fresh_control'] = before == capture(model, optimizer, torch, np)
    invalid_model = copy.deepcopy(model)
    invalid_optimizer = torch.optim.AdamW(invalid_model.parameters(), **options, foreach=False, fused=False)
    invalid_optimizer.load_state_dict(copy.deepcopy(optimizer.state_dict()))
    invalid_optimizer.state[invalid_model.project.weight]['exp_avg_sq'].flatten()[0] = -1
    invalid_before = capture(invalid_model, invalid_optimizer, torch, np)
    calls = []
    try:
        audit(invalid_model, lambda m: calls.append(True) or m(x), lambda y: y.square().mean(), optimizer=invalid_optimizer)
    except SaveScopeError as error:
        record['negative_state_error'] = str(error)
        checks['negative_variance_refuses_before_forward'] = not calls
    else:
        checks['negative_variance_refuses_before_forward'] = False
    checks['invalid_state_not_repaired_or_mutated'] = invalid_before == capture(invalid_model, invalid_optimizer, torch, np)

    def interrupted(m):
        m(x)
        raise RuntimeError('predeclared callback interruption')

    try:
        audit(model, interrupted, lambda y: y.square().mean(), optimizer=optimizer)
    except RuntimeError as error:
        checks['callback_exception_preserved'] = str(error) == 'predeclared callback interruption'
    else:
        checks['callback_exception_preserved'] = False
    checks['caller_unchanged_after_callback_error'] = before == capture(model, optimizer, torch, np)
    record.update(checks=checks, audit=result, fresh_control=fresh, input_receipt=before,
                  runtime={'python': sys.version, 'torch': torch.__version__, 'numpy': np.__version__})
    trajectory.append({'label': 'native_dense_reference_after', 'values': reference_after,
                       'gradients': direct_gradient_values})
    path = output / 'trajectory.json'
    path.write_text(json.dumps(trajectory, allow_nan=False) + '\n', encoding='utf-8')
    record['trajectory_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_report(as_report(result, title='Accumulated AdamW / fixed tiny CPU fixture', run_label='seed ' + str(protocol['seed'])), output / 'viewer')
    assert all(checks.values()), [key for key, value in checks.items() if not value]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', default='fixtures/savescope-optimizer-state/protocol.json')
    parser.add_argument('--freeze', default='fixtures/savescope-optimizer-state/implementation.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    protocol_path, freeze_path, output = Path(args.protocol), Path(args.freeze), Path(args.output)
    freeze = json.loads(freeze_path.read_bytes())
    for name, expected in freeze['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    assert freeze['protocol_sha256'] == hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(protocol_path.read_bytes())
    record = {'kind': protocol['kind'], 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'status': 'running', 'protocol_sha256': freeze['protocol_sha256'],
              'implementation_freeze_sha256': hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
              'warmup_updates_completed': 0, 'direct_reference_updates_completed': 0,
              'stateful_arms_completed': 0, 'fresh_control_arms_completed': 0,
              'actual_suites': 1, 'retries': 0, 'pretrained_model_loads': 0,
              'claim_limit': protocol['claim_limit']}
    try:
        execute(protocol, record, output)
        record['status'] = 'passed'
    except BaseException as error:
        record.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        record['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        record['payload_sha256'] = digest(record)
        (output / 'report.json').write_text(json.dumps(record, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': record['status'], 'checks': len(record['checks']), 'payload_sha256': record['payload_sha256']}))


if __name__ == '__main__':
    main()
