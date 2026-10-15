# Residual depth-bank budget probe

Independent synthetic NumPy diagnostic; results measure approximation error against full depth mixing.

Configuration: depths [32, 128]; 64 tokens; dimension 64; seeds [0, 1, 2]; budget 16; temperature 1.0.

Formula: `softmax_depth(dot(RMSNorm(bank[d,t]), query[t]) / temperature) @ bank[:,t]`. Default temperature 1.0 means an unscaled dot product.

`fixed_random` shares one seeded random vector across tokens; it is not learned.

**Query warning:** `focused_oracle` reads the full bank to select a target depth per token. It is a token-dependent oracle stress test, not the shared learned AttnRes pseudo-query or a deployable retention policy.

Each row averages metrics over seeds. P95 is first computed across tokens within each seed, then averaged.

| Depth | Distribution | Query | Method | Relative L2 | Token cosine | P95 token rel. L2 | Logits | Bank KiB | Dequant temp KiB |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 32 | random | fixed_random | full | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | random | fixed_random | recent_subset | 0.94785 | 0.56176 | 1.49071 | 1024 | 256.00 | 0.00 |
| 32 | random | fixed_random | stride_subset | 0.95674 | 0.55531 | 1.50868 | 1024 | 256.00 | 0.00 |
| 32 | random | fixed_random | block_sum | 1.34896 | 0.46051 | 2.10253 | 1024 | 256.00 | 0.00 |
| 32 | random | fixed_random | nonuniform_block_sum | 1.36331 | 0.47599 | 2.28511 | 1024 | 256.00 | 0.00 |
| 32 | random | fixed_random | int8 | 0.01371 | 0.99988 | 0.03406 | 2048 | 136.00 | 512.00 |
| 32 | random | fixed_random | oracle_topk | 0.00005 | 1.00000 | 0.00011 | 2048 | 512.00 | 0.00 |
| 32 | random | focused_oracle | full | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | random | focused_oracle | recent_subset | 0.72653 | 0.66829 | 1.15982 | 1024 | 256.00 | 0.00 |
| 32 | random | focused_oracle | stride_subset | 0.77101 | 0.61863 | 1.16465 | 1024 | 256.00 | 0.00 |
| 32 | random | focused_oracle | block_sum | 0.83386 | 0.77056 | 0.95889 | 1024 | 256.00 | 0.00 |
| 32 | random | focused_oracle | nonuniform_block_sum | 0.89748 | 0.77036 | 1.27249 | 1024 | 256.00 | 0.00 |
| 32 | random | focused_oracle | int8 | 0.00595 | 0.99998 | 0.00749 | 2048 | 136.00 | 512.00 |
| 32 | random | focused_oracle | oracle_topk | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | correlated | fixed_random | full | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | correlated | fixed_random | recent_subset | 0.07782 | 0.99696 | 0.13628 | 1024 | 256.00 | 0.00 |
| 32 | correlated | fixed_random | stride_subset | 0.00728 | 0.99997 | 0.01184 | 1024 | 256.00 | 0.00 |
| 32 | correlated | fixed_random | block_sum | 0.99998 | 1.00000 | 1.00040 | 1024 | 256.00 | 0.00 |
| 32 | correlated | fixed_random | nonuniform_block_sum | 1.05642 | 1.00000 | 1.56165 | 1024 | 256.00 | 0.00 |
| 32 | correlated | fixed_random | int8 | 0.00149 | 1.00000 | 0.00208 | 2048 | 136.00 | 512.00 |
| 32 | correlated | fixed_random | oracle_topk | 0.02365 | 0.99972 | 0.03496 | 2048 | 512.00 | 0.00 |
| 32 | correlated | focused_oracle | full | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | correlated | focused_oracle | recent_subset | 0.05501 | 0.99848 | 0.09991 | 1024 | 256.00 | 0.00 |
| 32 | correlated | focused_oracle | stride_subset | 0.00576 | 0.99998 | 0.00743 | 1024 | 256.00 | 0.00 |
| 32 | correlated | focused_oracle | block_sum | 0.99992 | 1.00000 | 1.00000 | 1024 | 256.00 | 0.00 |
| 32 | correlated | focused_oracle | nonuniform_block_sum | 0.88877 | 1.00000 | 1.32144 | 1024 | 256.00 | 0.00 |
| 32 | correlated | focused_oracle | int8 | 0.00116 | 1.00000 | 0.00147 | 2048 | 136.00 | 512.00 |
| 32 | correlated | focused_oracle | oracle_topk | 0.03907 | 0.99928 | 0.04388 | 2048 | 512.00 | 0.00 |
| 32 | rare_spikes | fixed_random | full | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | rare_spikes | fixed_random | recent_subset | 1.34202 | 0.57163 | 1.50335 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | fixed_random | stride_subset | 1.30357 | 0.55737 | 1.53915 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | fixed_random | block_sum | 1.85894 | 0.48825 | 4.49742 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | fixed_random | nonuniform_block_sum | 1.77530 | 0.48440 | 6.38521 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | fixed_random | int8 | 0.01957 | 0.99988 | 0.03813 | 2048 | 136.00 | 512.00 |
| 32 | rare_spikes | fixed_random | oracle_topk | 0.00004 | 1.00000 | 0.00013 | 2048 | 512.00 | 0.00 |
| 32 | rare_spikes | focused_oracle | full | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 32 | rare_spikes | focused_oracle | recent_subset | 0.69761 | 0.62725 | 0.99753 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | focused_oracle | stride_subset | 0.68832 | 0.64606 | 0.99750 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | focused_oracle | block_sum | 0.01876 | 0.99982 | 0.02288 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | focused_oracle | nonuniform_block_sum | 0.02074 | 0.99978 | 0.03003 | 1024 | 256.00 | 0.00 |
| 32 | rare_spikes | focused_oracle | int8 | 0.00595 | 0.99998 | 0.00762 | 2048 | 136.00 | 512.00 |
| 32 | rare_spikes | focused_oracle | oracle_topk | 0.00000 | 1.00000 | 0.00000 | 2048 | 512.00 | 0.00 |
| 128 | random | fixed_random | full | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | random | fixed_random | recent_subset | 1.31555 | 0.22234 | 1.77710 | 1024 | 256.00 | 0.00 |
| 128 | random | fixed_random | stride_subset | 1.29541 | 0.24118 | 1.80041 | 1024 | 256.00 | 0.00 |
| 128 | random | fixed_random | block_sum | 3.07826 | 0.17706 | 4.86384 | 1024 | 256.00 | 0.00 |
| 128 | random | fixed_random | nonuniform_block_sum | 3.13896 | 0.19259 | 5.54407 | 1024 | 256.00 | 0.00 |
| 128 | random | fixed_random | int8 | 0.01480 | 0.99987 | 0.03412 | 8192 | 544.00 | 2048.00 |
| 128 | random | fixed_random | oracle_topk | 0.00139 | 1.00000 | 0.00349 | 8192 | 2048.00 | 0.00 |
| 128 | random | focused_oracle | full | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | random | focused_oracle | recent_subset | 1.01774 | 0.33004 | 1.17937 | 1024 | 256.00 | 0.00 |
| 128 | random | focused_oracle | stride_subset | 1.00184 | 0.35090 | 1.17391 | 1024 | 256.00 | 0.00 |
| 128 | random | focused_oracle | block_sum | 2.10111 | 0.43891 | 2.42459 | 1024 | 256.00 | 0.00 |
| 128 | random | focused_oracle | nonuniform_block_sum | 2.30120 | 0.43019 | 3.08830 | 1024 | 256.00 | 0.00 |
| 128 | random | focused_oracle | int8 | 0.00605 | 0.99998 | 0.00733 | 8192 | 544.00 | 2048.00 |
| 128 | random | focused_oracle | oracle_topk | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | correlated | fixed_random | full | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | correlated | fixed_random | recent_subset | 0.12359 | 0.99270 | 0.17383 | 1024 | 256.00 | 0.00 |
| 128 | correlated | fixed_random | stride_subset | 0.00943 | 0.99995 | 0.01644 | 1024 | 256.00 | 0.00 |
| 128 | correlated | fixed_random | block_sum | 7.00004 | 1.00000 | 7.00178 | 1024 | 256.00 | 0.00 |
| 128 | correlated | fixed_random | nonuniform_block_sum | 7.15176 | 1.00000 | 9.69012 | 1024 | 256.00 | 0.00 |
| 128 | correlated | fixed_random | int8 | 0.00075 | 1.00000 | 0.00104 | 8192 | 544.00 | 2048.00 |
| 128 | correlated | fixed_random | oracle_topk | 0.05936 | 0.99826 | 0.09466 | 8192 | 2048.00 | 0.00 |
| 128 | correlated | focused_oracle | full | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | correlated | focused_oracle | recent_subset | 0.10387 | 0.99478 | 0.15063 | 1024 | 256.00 | 0.00 |
| 128 | correlated | focused_oracle | stride_subset | 0.00682 | 0.99998 | 0.00920 | 1024 | 256.00 | 0.00 |
| 128 | correlated | focused_oracle | block_sum | 6.99960 | 1.00000 | 6.99991 | 1024 | 256.00 | 0.00 |
| 128 | correlated | focused_oracle | nonuniform_block_sum | 6.31947 | 1.00000 | 8.60558 | 1024 | 256.00 | 0.00 |
| 128 | correlated | focused_oracle | int8 | 0.00059 | 1.00000 | 0.00074 | 8192 | 544.00 | 2048.00 |
| 128 | correlated | focused_oracle | oracle_topk | 0.07792 | 0.99717 | 0.09438 | 8192 | 2048.00 | 0.00 |
| 128 | rare_spikes | fixed_random | full | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | rare_spikes | fixed_random | recent_subset | 1.02455 | 0.22126 | 1.77788 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | fixed_random | stride_subset | 1.07056 | 0.23967 | 1.86013 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | fixed_random | block_sum | 3.60547 | 0.20385 | 26.92860 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | fixed_random | nonuniform_block_sum | 3.33316 | 0.22125 | 24.09095 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | fixed_random | int8 | 0.01349 | 0.99987 | 0.03597 | 8192 | 544.00 | 2048.00 |
| 128 | rare_spikes | fixed_random | oracle_topk | 0.00130 | 0.99998 | 0.00728 | 8192 | 2048.00 | 0.00 |
| 128 | rare_spikes | focused_oracle | full | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |
| 128 | rare_spikes | focused_oracle | recent_subset | 0.94289 | 0.32846 | 0.99762 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | focused_oracle | stride_subset | 0.94031 | 0.32647 | 0.99782 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | focused_oracle | block_sum | 0.04969 | 0.99875 | 0.05886 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | focused_oracle | nonuniform_block_sum | 0.05588 | 0.99842 | 0.07277 | 1024 | 256.00 | 0.00 |
| 128 | rare_spikes | focused_oracle | int8 | 0.00587 | 0.99998 | 0.00712 | 8192 | 544.00 | 2048.00 |
| 128 | rare_spikes | focused_oracle | oracle_topk | 0.00000 | 1.00000 | 0.00000 | 8192 | 2048.00 | 0.00 |

## Scope and limitations

- Synthetic inference-only diagnostic; no training, real model activations, quality benchmark, or paper reproduction.
- Default temperature=1.0 uses the unscaled RMSNorm-key dot product; other temperatures are optional probe choices. Pseudo queries are not trained model parameters.
- fixed_random shares one random vector across tokens, but it is not a learned AttnRes query. focused_oracle is token-dependent and uses full-bank information; it is an oracle stress test, not the shared learned AttnRes pseudo-query.
- block_sum constructs disjoint depth sums offline; it is not trained hierarchical Block AttnRes and has a different magnitude distribution.
- nonuniform_block_sum uses larger earlier groups and smaller recent groups; this is a hand-designed offline grouping proxy, not a validated schedule.
- oracle_topk scores and retains the full bank; its selected output does not save persistent bank memory or logit work.
- Logical persistent bank bytes exclude query, RMSNorm keys, logits, output, selection buffers, allocator overhead, and upstream storage. They are not GPU peak memory.
- int8 counts one float32 scale per depth/token vector and a full float32 dequantized bank temporary; NumPy may allocate further temporary buffers.
- Subset and block costs assume the retained bank is already prepared; offline construction costs and retention policy are excluded.
