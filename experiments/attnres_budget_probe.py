"""Independent NumPy diagnostic of depth-bank attention and storage approximations.

This is a synthetic, offline approximation study, not AttnRes training or a paper
reproduction. Each token attends only to its own vectors across residual depth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


EPS = 1e-6


def rms_norm(values: np.ndarray) -> np.ndarray:
    """Normalize each vector without learned affine parameters."""
    return values / np.sqrt(np.mean(values * values, axis=-1, keepdims=True) + EPS)


def depth_logits(bank: np.ndarray, query: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """bank [depth, token, feature], query [token, feature] -> [depth, token]."""
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    return np.einsum("dtf,tf->dt", rms_norm(bank), query) / temperature


def weighted_mix(bank: np.ndarray, logits: np.ndarray) -> np.ndarray:
    weights = np.exp(logits - np.max(logits, axis=0, keepdims=True))
    weights /= weights.sum(axis=0, keepdims=True)
    return np.einsum("dt,dtf->tf", weights, bank)


def full_mix(bank: np.ndarray, query: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    return weighted_mix(bank, depth_logits(bank, query, temperature))


def quantize_vectors(bank: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric per-vector int8; float32 scales include exact zero vectors."""
    scales = np.max(np.abs(bank), axis=-1, keepdims=True) / np.float32(127.0)
    scales = np.where(scales == 0, np.float32(1.0), scales).astype(np.float32)
    return np.clip(np.rint(bank / scales), -127, 127).astype(np.int8), scales


def budget_record(depth: int, tokens: int, dim: int, stored_depth: int,
                  *, int8: bool = False, full_logits: bool = False) -> dict:
    vector_count = stored_depth * tokens
    return {
        "logit_evaluations": (depth if full_logits else stored_depth) * tokens,
        "logical_persistent_bank_bytes": vector_count * (dim + 4 if int8 else dim * 4),
        "dequantization_temporary_bytes": depth * tokens * dim * 4 if int8 else 0,
    }


def nonuniform_blocks(bank: np.ndarray, count: int) -> list[np.ndarray]:
    """Give earlier depth groups more vectors, preserving finer recent depth."""
    remaining = bank.shape[0] - count
    weights = np.arange(count, 0, -1, dtype=np.float64)
    allocation = remaining * weights / weights.sum()
    extra = np.floor(allocation).astype(np.int64)
    spare = remaining - int(extra.sum())
    order = np.argsort(-(allocation - extra), kind="stable")
    extra[order[:spare]] += 1
    sizes = extra + 1
    return list(np.split(bank, np.cumsum(sizes)[:-1], axis=0))


def evaluate_method(bank: np.ndarray, query: np.ndarray, method: str,
                    budget: int, temperature: float = 1.0) -> tuple[np.ndarray, dict]:
    depth, tokens, dim = bank.shape
    if budget < 1:
        raise ValueError("budget must be positive")
    keep = min(budget, depth)
    if method == "full":
        return full_mix(bank, query, temperature), budget_record(depth, tokens, dim, depth)
    if method == "recent_subset":
        selected = bank[-keep:]
        return full_mix(selected, query, temperature), budget_record(depth, tokens, dim, keep)
    if method == "stride_subset":
        indices = np.linspace(0, depth - 1, keep, dtype=np.int64)
        return full_mix(bank[indices], query, temperature), budget_record(depth, tokens, dim, keep)
    if method in ("block_sum", "nonuniform_block_sum"):
        # Offline depth sums are a proxy, not the trained hierarchical Block AttnRes.
        parts = (np.array_split(bank, keep) if method == "block_sum"
                 else nonuniform_blocks(bank, keep))
        blocks = np.stack([part.sum(axis=0) for part in parts])
        return full_mix(blocks, query, temperature), budget_record(depth, tokens, dim, keep)
    if method == "int8":
        packed, scales = quantize_vectors(bank)
        dequantized = packed.astype(np.float32) * scales
        return full_mix(dequantized, query, temperature), budget_record(
            depth, tokens, dim, depth, int8=True)
    if method == "oracle_topk":
        logits = depth_logits(bank, query, temperature)
        indices = np.argpartition(logits, depth - keep, axis=0)[-keep:]
        selected = np.take_along_axis(bank, indices[..., None], axis=0)
        selected_logits = np.take_along_axis(logits, indices, axis=0)
        # Selection is per token and still reads and scores the complete bank.
        return weighted_mix(selected, selected_logits), budget_record(
            depth, tokens, dim, depth, full_logits=True)
    raise ValueError(f"unknown method: {method}")


def make_bank(depth: int, tokens: int, dim: int, seed: int,
              distribution: str) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if distribution == "random":
        bank = rng.normal(size=(depth, tokens, dim))
    elif distribution == "correlated":
        shared = rng.normal(size=(tokens, dim))
        innovations = rng.normal(size=(depth, tokens, dim))
        walk = np.cumsum(innovations, axis=0) / np.sqrt(depth)
        bank = shared[None, :, :] + 0.25 * walk
    elif distribution == "rare_spikes":
        bank = rng.normal(scale=0.15, size=(depth, tokens, dim))
        spike_depth = rng.integers(0, depth, size=tokens)
        bank[spike_depth, np.arange(tokens)] += rng.normal(scale=8.0, size=(tokens, dim))
    else:
        raise ValueError(f"unknown distribution: {distribution}")
    return bank.astype(np.float32)


def make_query(bank: np.ndarray, seed: int, query_type: str) -> np.ndarray:
    if query_type == "fixed_random":
        shared = np.random.default_rng(seed + 1_000_003).normal(
            size=bank.shape[-1]).astype(np.float32)
        return np.broadcast_to(shared, bank.shape[1:])
    if query_type in ("focused_oracle", "focused"):
        # Synthetic oracle query: point at the largest-norm vector of each token.
        strongest = np.argmax(np.sum(bank * bank, axis=-1), axis=0)
        return rms_norm(bank[strongest, np.arange(bank.shape[1])])
    raise ValueError(f"unknown query type: {query_type}")


def error_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict:
    delta = np.linalg.norm(candidate - reference, axis=-1)
    ref_norm = np.linalg.norm(reference, axis=-1)
    cand_norm = np.linalg.norm(candidate, axis=-1)
    denominator = ref_norm * cand_norm
    cosine = np.divide(np.sum(reference * candidate, axis=-1), denominator,
                       out=np.zeros_like(ref_norm), where=denominator > EPS)
    both_zero = (ref_norm <= EPS) & (cand_norm <= EPS)
    cosine[both_zero] = 1.0
    token_relative_error = delta / np.maximum(ref_norm, EPS)
    return {
        "relative_l2": float(np.linalg.norm(candidate - reference)
                             / max(float(np.linalg.norm(reference)), EPS)),
        "mean_token_cosine": float(np.clip(cosine, -1, 1).mean()),
        "p95_token_relative_l2": float(np.percentile(token_relative_error, 95)),
    }


METHODS = ("full", "recent_subset", "stride_subset", "block_sum",
           "nonuniform_block_sum", "int8", "oracle_topk")
DISTRIBUTIONS = ("random", "correlated", "rare_spikes")
QUERY_TYPES = ("fixed_random", "focused_oracle")


def run_probe(depths: list[int], tokens: int, dim: int, seeds: list[int],
              budget: int, temperature: float = 1.0) -> dict:
    if not depths or any(d < 1 for d in depths) or tokens < 1 or dim < 1 or budget < 1:
        raise ValueError("depths, tokens, dim, and budget must be positive")
    if not seeds or any(seed < 0 for seed in seeds):
        raise ValueError("provide at least one nonnegative seed")
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    records = []
    for depth in depths:
        for seed in seeds:
            for distribution in DISTRIBUTIONS:
                bank = make_bank(depth, tokens, dim, seed, distribution)
                for query_type in QUERY_TYPES:
                    query = make_query(bank, seed, query_type)
                    reference = full_mix(bank, query, temperature)
                    for method in METHODS:
                        candidate, costs = evaluate_method(bank, query, method, budget, temperature)
                        records.append({
                            "depth": depth, "tokens": tokens, "dim": dim,
                            "seed": seed, "distribution": distribution,
                            "query": query_type, "method": method,
                            "query_uses_full_bank_oracle": query_type == "focused_oracle",
                            "effective_budget": min(budget, depth),
                            **error_metrics(reference, candidate), **costs,
                        })
    return {
        "schema_version": 1,
        "experiment": "independent synthetic residual depth-bank budget diagnostic",
        "config": {"depths": depths, "tokens": tokens, "dim": dim,
                   "seeds": seeds, "budget": budget, "temperature": temperature,
                   "dtype": "float32"},
        "formula": "softmax_depth(dot(RMSNorm(bank[d,t]), query[t]) / temperature) @ bank[:,t]",
        "pseudo_queries": {
            "fixed_random": "One seeded random vector shared across all tokens, independent of bank values; not learned.",
            "focused_oracle": "Token-dependent full-bank oracle: RMSNorm of the largest-norm depth vector for each token; not the shared learned AttnRes pseudo-query.",
        },
        "limitations": [
            "Synthetic inference-only diagnostic; no training, real model activations, quality benchmark, or paper reproduction.",
            "Default temperature=1.0 uses the unscaled RMSNorm-key dot product; other temperatures are optional probe choices. Pseudo queries are not trained model parameters.",
            "fixed_random shares one random vector across tokens, but it is not a learned AttnRes query. focused_oracle is token-dependent and uses full-bank information; it is an oracle stress test, not the shared learned AttnRes pseudo-query.",
            "block_sum constructs disjoint depth sums offline; it is not trained hierarchical Block AttnRes and has a different magnitude distribution.",
            "nonuniform_block_sum uses larger earlier groups and smaller recent groups; this is a hand-designed offline grouping proxy, not a validated schedule.",
            "oracle_topk scores and retains the full bank; its selected output does not save persistent bank memory or logit work.",
            "Logical persistent bank bytes exclude query, RMSNorm keys, logits, output, selection buffers, allocator overhead, and upstream storage. They are not GPU peak memory.",
            "int8 counts one float32 scale per depth/token vector and a full float32 dequantized bank temporary; NumPy may allocate further temporary buffers.",
            "Subset and block costs assume the retained bank is already prepared; offline construction costs and retention policy are excluded.",
        ],
        "records": records,
    }


def render_markdown(result: dict) -> str:
    config = result["config"]
    lines = ["# Residual depth-bank budget probe", "",
             "Independent synthetic NumPy diagnostic; results measure approximation error against full depth mixing.", "",
             f"Configuration: depths {config['depths']}; {config['tokens']} tokens; dimension {config['dim']}; seeds {config['seeds']}; budget {config['budget']}; temperature {config['temperature']}.", "",
             f"Formula: `{result['formula']}`. Default temperature 1.0 means an unscaled dot product.", "",
             "`fixed_random` shares one seeded random vector across tokens; it is not learned.", "",
             "**Query warning:** `focused_oracle` reads the full bank to select a target depth per token. It is a token-dependent oracle stress test, not the shared learned AttnRes pseudo-query or a deployable retention policy.", "",
             "Each row averages metrics over seeds. P95 is first computed across tokens within each seed, then averaged.", "",
             "| Depth | Distribution | Query | Method | Relative L2 | Token cosine | P95 token rel. L2 | Logits | Bank KiB | Dequant temp KiB |",
             "|---:|---|---|---|---:|---:|---:|---:|---:|---:|"]
    records = result["records"]
    for depth in config["depths"]:
        for distribution in DISTRIBUTIONS:
            for query_type in QUERY_TYPES:
                for method in METHODS:
                    group = [r for r in records if r["depth"] == depth
                             and r["distribution"] == distribution and r["query"] == query_type
                             and r["method"] == method]
                    mean = lambda key: float(np.mean([r[key] for r in group]))
                    lines.append(
                        f"| {depth} | {distribution} | {query_type} | {method} | "
                        f"{mean('relative_l2'):.5f} | {mean('mean_token_cosine'):.5f} | "
                        f"{mean('p95_token_relative_l2'):.5f} | {mean('logit_evaluations'):.0f} | "
                        f"{mean('logical_persistent_bank_bytes') / 1024:.2f} | "
                        f"{mean('dequantization_temporary_bytes') / 1024:.2f} |")
    lines.extend(["", "## Scope and limitations", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines) + "\n"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not np.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depths", type=positive_int, nargs="+", default=[32, 128])
    parser.add_argument("--tokens", type=positive_int, default=64)
    parser.add_argument("--dim", type=positive_int, default=64)
    parser.add_argument("--seeds", type=nonnegative_int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--budget", type=positive_int, default=16)
    parser.add_argument("--temperature", type=positive_float, default=1.0,
                        help="logit divisor; default 1.0 (unscaled); pass sqrt(dim) numerically for scaled logits")
    parser.add_argument("--output", type=Path, default=Path("results/attnres-budget"),
                        help="output filename prefix; writes .json and .md")
    args = parser.parse_args()
    result = run_probe(args.depths, args.tokens, args.dim, args.seeds, args.budget,
                       args.temperature)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output.with_suffix(".json")
    md_path = args.output.with_suffix(".md")
    json_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    md_path.write_text(render_markdown(result), encoding="utf-8", newline="\n")
    print(f"Wrote {len(result['records'])} measurements: {json_path} and {md_path}")


if __name__ == "__main__":
    main()
