"""Engineering fixtures only; never load/download the pretrained model."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import activation_cost_probe as probe

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
TRANSFORMERS_AVAILABLE = importlib.util.find_spec("transformers") is not None


def fixture(directory):
    directory = Path(directory)
    train = {"schema_version": 1, "train": [list(range(i, i + 65)) for i in range(128)]}
    holdout = {"schema_version": 1, "holdout": [list(range(1000 + i, 1065 + i)) for i in range(64)]}
    probe.write_new(directory / "train.json", train)
    probe.write_new(directory / "holdout.json", holdout)
    manifest = {"schema_version": 1, "model_id": probe.MODEL_ID, "model_revision": probe.MODEL_REVISION,
                "train_sha256": probe.file_hash(directory / "train.json"),
                "holdout_sha256": probe.file_hash(directory / "holdout.json"),
                "tokenizer_sha256": probe.PINNED_ASSETS["tokenizer.json"][1],
                "train_source_sha256": "a" * 64, "holdout_source_sha256": "b" * 64}
    probe.write_new(directory / "manifest.json", manifest)
    protocol = {"schema_version": 1, "predeclared_at": "2020-01-01T00:00:00+00:00",
                "config": probe.preset_config(), "config_sha256": probe.digest(probe.preset_config()),
                "train_sha256": manifest["train_sha256"], "holdout_sha256": manifest["holdout_sha256"],
                "manifest_sha256": probe.file_hash(directory / "manifest.json"),
                "preparation_script_sha256": probe.file_hash(probe.ROOT / "scripts/prepare_activation_cost.py"),
                "frozen_dependencies_sha256": {"scripts/capture_real_activation.py": probe.file_hash(probe.ROOT / "scripts/capture_real_activation.py")},
                "schedules": {}}
    for seed in probe.SEEDS:
        full = probe.batch_schedule(128, 4096, 2, seed)
        protocol["schedules"][str(seed)] = {"time_schedule_sha256": probe.digest(full),
            "token_schedule_sha256": probe.digest(full[:64]), "token_batches": full[:64]}
    probe.write_new(directory / "protocol.json", protocol)
    freeze = {"schema_version": 1, "frozen_at": "2020-01-02T00:00:00+00:00",
              "protocol_sha256": probe.file_hash(directory / "protocol.json"),
              "new_source_files_sha256": {p: probe.file_hash(probe.ROOT / p) for p in probe.SOURCE_PATHS},
              "frozen_dependencies_sha256": protocol["frozen_dependencies_sha256"]}
    probe.write_new(directory / "implementation.json", freeze)
    return directory


class ProtocolTests(unittest.TestCase):
    def test_predeclared_real_config_and_all_schedule_pins_match(self):
        protocol = probe.read_small(probe.ROOT / "fixtures/activation-cost/protocol.json")
        self.assertEqual(protocol["config"], probe.preset_config())
        self.assertEqual(protocol["config_sha256"], probe.digest(probe.preset_config()))
        for seed in probe.SEEDS:
            schedule = probe.batch_schedule(128, 4096, 2, seed)
            self.assertEqual(probe.digest(schedule), protocol["schedules"][str(seed)]["time_schedule_sha256"])
            self.assertEqual(schedule[:64], protocol["schedules"][str(seed)]["token_batches"])
            for start in (0, 64, 128, 4032):
                self.assertEqual(sorted(i for b in schedule[start:start + 64] for i in b), list(range(128)))

    def test_training_validation_never_opens_heldout_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = fixture(tmp)
            (directory / "holdout.json").unlink()
            probe.validate_fixture(directory, verify_holdout=False)
            with self.assertRaises(FileNotFoundError):
                probe.validate_fixture(directory, verify_holdout=True)

    def test_tampered_extra_frozen_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = fixture(tmp)
            freeze = probe.read_small(directory / "implementation.json")
            freeze["frozen_dependencies_sha256"]["experiments/activation_history_probe.py"] = "0" * 64
            (directory / "implementation.json").write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra source"):
                probe.validate_fixture(directory)

    def test_training_token_hash_and_boolean_tokens_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = fixture(tmp)
            train = probe.read_small(directory / "train.json")
            train["train"][0][0] = True
            (directory / "train.json").write_text(json.dumps(train), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "train file hash"):
                probe.validate_fixture(directory)
            with self.assertRaisesRegex(ValueError, "token block"):
                probe.load_blocks(directory / "train.json", "train", 128)

    def test_time_window_excludes_step_cap_and_boundaries(self):
        self.assertFalse(probe.classify_time(59.999, 100)["valid"])
        self.assertTrue(probe.classify_time(60.0, 100)["valid"])
        self.assertTrue(probe.classify_time(61.0, 100)["valid"])
        self.assertFalse(probe.classify_time(61.000001, 100)["valid"])
        self.assertFalse(probe.classify_time(60.5, 4096)["valid"])
        self.assertFalse(probe.classify_time(60.5, 0)["valid"])

    def test_job_order_is_complete_paired_and_alternating(self):
        jobs = probe.job_order()
        self.assertEqual(len(jobs), 12)
        self.assertEqual(len({tuple(j.values()) for j in jobs}), 12)
        self.assertEqual([j["method"] for j in jobs[:6:2]], [probe.METHODS[0], probe.METHODS[1], probe.METHODS[0]])
        self.assertEqual([j["method"] for j in jobs[6::2]], [probe.METHODS[1], probe.METHODS[0], probe.METHODS[1]])

    def test_failure_receipt_is_preserved_and_output_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "worker"
            with mock.patch.object(probe, "validate_fixture", side_effect=ValueError("deliberate fixture rejection")):
                with self.assertRaisesRegex(ValueError, "fixture rejection"):
                    probe.training_worker("unused", "unused", output, "token", probe.METHODS[0], 503)
                original = (output / "failure.json").read_bytes()
                with self.assertRaises(FileExistsError):
                    probe.training_worker("unused", "unused", output, "token", probe.METHODS[0], 503)
                self.assertEqual((output / "failure.json").read_bytes(), original)

    def test_release_rejects_missing_duplicate_or_tampered_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checkpoint"; p.write_bytes(b"engineering dummy, not model weights")
            endpoints = [{**j, "checkpoint_path": str(p), "checkpoint_sha256": probe.file_hash(p)} for j in probe.job_order()]
            release = {"all_training_completed": True, "endpoints": endpoints}
            self.assertEqual(len(probe.validate_release(release)), 12)
            with self.assertRaisesRegex(ValueError, "every declared"):
                probe.validate_release({**release, "endpoints": endpoints[:-1]})
            with self.assertRaisesRegex(ValueError, "every declared"):
                probe.validate_release({**release, "endpoints": endpoints[:-1] + [endpoints[0]]})
            p.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checkpoint hash"):
                probe.validate_release(release)

    def test_training_samples_filter_setup_and_include_boundary_gaps(self):
        samples = [{"sample_perf_counter": t, "resident_bytes": rss, "private_bytes": None}
                   for t, rss in [(9, 999), (10.2, 30), (10.5, 40), (12, 9999)]]
        out = probe.training_sample_summary(samples, 10, 11)
        self.assertEqual(out["samples_count"], 2)
        self.assertEqual(out["sampled_max_resident_bytes"], 40)
        self.assertAlmostEqual(out["largest_gap_including_boundaries_seconds"], 0.5)

    def test_one_bad_seed_or_invalid_time_control_cannot_be_averaged_away(self):
        workers, endpoints = [], []
        for j in probe.job_order():
            compressed = j["method"] == probe.METHODS[1]
            workers.append({**j, "training_loop_wall_seconds": 1.0 if compressed else 2.0,
                "memory_through_training_completion": {"peak_bytes": 10 if compressed else 20},
                "time_control": {"valid": not (j["arm"] == "time" and j["seed"] == 907 and compressed)}})
            nll = 2.0 if compressed else 3.0
            if j["arm"] == "token" and j["seed"] == 701 and compressed:
                nll = 3.00001
            endpoints.append({**j, "evaluation": {"mean_nll": nll}})
        outcome = probe.directional_screens(workers, {"initial": {"mean_nll": 4.0}, "endpoints": endpoints})
        self.assertFalse(outcome["all_token_directional_screens_passed"])
        self.assertFalse(outcome["all_time_controls_and_directional_screens_passed"])


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU Torch absent")
class TinyTorchTests(unittest.TestCase):
    def tiny(self):
        import torch
        class Tiny(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embed = torch.nn.Embedding(17, 16)
                self.norm = torch.nn.LayerNorm(16)
                self.mlp = torch.nn.Linear(16, 32)
                self.head = torch.nn.Linear(32, 17)
            def forward(self, input_ids, use_cache=False):
                return SimpleNamespace(logits=self.head(self.mlp(self.norm(self.embed(input_ids)))))
        torch.manual_seed(17)
        return Tiny().eval()

    def test_codec_alias_zero_nearzero_nonfinite_and_no_callback_clocks(self):
        import torch
        p = torch.nn.Parameter(torch.ones(16, 32))
        codec = probe.CostCodec([p])
        with mock.patch.object(probe.time, "perf_counter", side_effect=AssertionError("no callback timer")):
            self.assertEqual(probe.storage_key(codec.pack(p.t())), probe.storage_key(p))
            for x in (torch.zeros(16, 32), torch.full((16, 32), 1e-20)):
                q = codec.pack(x)
                self.assertTrue(torch.isfinite(codec.unpack(q)).all())
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                codec.pack(torch.full((16, 32), float("nan")))
        self.assertFalse(hasattr(codec, "counts"))
        self.assertFalse(hasattr(codec, "pack_seconds"))

    def test_scope_restores_instance_attributes_on_failure(self):
        model = self.tiny()
        original = model.norm.forward
        self.assertNotIn("forward", model.norm.__dict__)
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            with probe.preserve_scopes([("norm", model.norm)]):
                raise RuntimeError("deliberate")
        self.assertNotIn("forward", model.norm.__dict__)
        self.assertEqual(model.norm.forward, original)

    def test_light_and_profile_codecs_match_established_exact_norm_scope_gradients(self):
        import torch
        from experiments.activation_training_probe import SavedActivationCodec
        from experiments.activation_norm_gradient_probe import named_layernorm_hooks
        models = [self.tiny() for _ in range(3)]
        tokens = torch.arange(130).reshape(2, 65) % 17
        reference = models[0]
        old = SavedActivationCodec(list(reference.parameters()), "int8_saved_tensors")
        with named_layernorm_hooks(reference, list(reference.parameters()), "dense"):
            loss = probe.forward_loss(reference, tokens, old)
            loss.backward()
        for model, cls in zip(models[1:], (probe.CostCodec, probe.ProfileCodec)):
            codec = cls(list(model.parameters()))
            with probe.preserve_scopes([("norm", model.norm)]):
                actual = probe.forward_loss(model, tokens, codec)
                actual.backward()
            self.assertTrue(torch.equal(loss.detach(), actual.detach()))
            for a, b in zip(reference.parameters(), model.parameters()):
                self.assertTrue(torch.equal(a.grad, b.grad))

    def test_native_dense_has_no_saved_hooks_and_makes_actual_updates(self):
        import torch
        model = self.tiny(); before = probe.parameter_hash(model)
        optimizer = probe.optimizer_for(model)
        tokens = torch.arange(130).reshape(2, 65) % 17
        config = {**probe.preset_config(), "token_steps": 2}
        with mock.patch.object(torch.autograd.graph, "saved_tensors_hooks", side_effect=AssertionError("native dense must not install hooks")):
            record = probe.training_loop(model, optimizer, [tokens, tokens], "token", "dense", [], config=config)
        self.assertEqual(record["steps_completed"], 2)
        self.assertNotEqual(probe.parameter_hash(model), before)
        self.assertEqual(probe.final_validity(model, optimizer, 2)["optimizer_counters"], [2] * len(list(model.parameters())))

    def test_profile_resets_inventories_each_step_and_matches_primary_parameters(self):
        import torch
        primary, profiled = self.tiny(), self.tiny()
        tokens = torch.arange(130).reshape(2, 65) % 17
        config = {**probe.preset_config(), "token_steps": 2}
        a = probe.training_loop(primary, probe.optimizer_for(primary), [tokens, tokens], "token", probe.METHODS[1], [("norm", primary.norm)], config=config)
        b = probe.training_loop(profiled, probe.optimizer_for(profiled), [tokens, tokens], "profile", probe.METHODS[1], [("norm", profiled.norm)], profile=True, config=config)
        self.assertEqual(probe.parameter_hash(primary), probe.parameter_hash(profiled))
        self.assertEqual(a["preupdate_batch_losses_recorded_after_updates"], b["preupdate_batch_losses_recorded_after_updates"])
        first, second = b["profile"]["steps"]
        self.assertEqual(first["outer"]["counts"]["save_calls"], second["outer"]["counts"]["save_calls"])
        self.assertEqual(first["preserved_scopes"]["norm"]["counts"].get("compressed_saves", 0), 0)


@unittest.skipUnless(TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE, "optional Torch/Transformers absent")
class ActualScopeLayoutTests(unittest.TestCase):
    def test_actual_attention_and_norm_save_masks_match_established_backward(self):
        import torch
        from transformers import GPTNeoXConfig
        from transformers.models.gpt_neox.modeling_gpt_neox import GPTNeoXAttention
        from experiments.activation_training_probe import SavedActivationCodec
        from experiments.activation_norm_gradient_probe import named_layernorm_hooks
        from experiments.activation_attention_gradient_probe import named_attention_hooks
        config = GPTNeoXConfig(hidden_size=16, intermediate_size=32, num_hidden_layers=1,
                              num_attention_heads=4, rotary_pct=0.5, attention_dropout=0.0)
        config._attn_implementation = "eager"
        class TinyAttentionLM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embed = torch.nn.Embedding(17, 16)
                self.norm = torch.nn.LayerNorm(16)
                self.attention = GPTNeoXAttention(config, layer_idx=0)
                self.mlp = torch.nn.Linear(16, 32)
                self.head = torch.nn.Linear(32, 17)
            def forward(self, input_ids, use_cache=False):
                x = self.norm(self.embed(input_ids))
                n = input_ids.shape[1]
                mask = torch.triu(torch.ones(n, n), diagonal=1)[None, None] * torch.finfo(x.dtype).min
                positions = (torch.ones(1, n, 2), torch.zeros(1, n, 2))
                x, _ = self.attention(x, attention_mask=mask, position_embeddings=positions)
                return SimpleNamespace(logits=self.head(self.mlp(x)))
        torch.manual_seed(19)
        reference = TinyAttentionLM().eval()
        actual = copy.deepcopy(reference)
        tokens = torch.arange(130).reshape(2, 65) % 17
        old = SavedActivationCodec(list(reference.parameters()), "int8_saved_tensors")
        with named_layernorm_hooks(reference, list(reference.parameters()), "dense"):
            with named_attention_hooks(reference, list(reference.parameters()), "dense"):
                expected_loss = probe.forward_loss(reference, tokens, old)
                expected_loss.backward()
        parameters = list(actual.parameters())
        outer = probe.ProfileCodec(parameters)
        scopes = {"norm": probe.ProfileCodec(parameters, False), "attention": probe.ProfileCodec(parameters, False)}
        with probe.preserve_scopes([("norm", actual.norm), ("attention", actual.attention)], scopes):
            actual_loss = probe.forward_loss(actual, tokens, outer)
            actual_loss.backward()
        self.assertTrue(torch.equal(expected_loss.detach(), actual_loss.detach()))
        for a, b in zip(reference.parameters(), actual.parameters()):
            self.assertTrue(torch.equal(a.grad, b.grad))
        for codec in scopes.values():
            self.assertGreater(codec.counts["save_calls"], 0)
            self.assertEqual(codec.counts["compressed_saves"], 0)

    def test_actual_attention_class_layout_count_without_pretrained_model(self):
        import torch
        from transformers import GPTNeoXConfig
        from transformers.models.gpt_neox.modeling_gpt_neox import GPTNeoXAttention
        config = GPTNeoXConfig(hidden_size=16, intermediate_size=32, num_hidden_layers=1, num_attention_heads=4)
        model = torch.nn.Module()
        model.norms = torch.nn.ModuleList([torch.nn.LayerNorm(16) for _ in range(13)])
        model.attentions = torch.nn.ModuleList([GPTNeoXAttention(config, layer_idx=i) for i in range(6)])
        norms, attentions = probe.preservation_modules(model)
        self.assertEqual((len(norms), len(attentions)), (13, 6))
        del model.norms[-1]
        with self.assertRaisesRegex(ValueError, "layout"):
            probe.preservation_modules(model)


if __name__ == "__main__":
    unittest.main()
