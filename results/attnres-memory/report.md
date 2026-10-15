# Synthetic residual-bank CPU memory probe

Fresh processes execute our NumPy inference diagnostic over prepacked synthetic banks. These are observed CPU process peaks and wall times.

Observed UTC: 2026-10-15T18:47:54.640247+00:00 to 2026-10-15T18:48:09.713767+00:00.

| Dense bank | Method | Repeats | Median operator ms | Median process peak MiB | Median post-import peak MiB | Median post-load peak MiB | Median post-load RSS MiB |
|---:|---|---:|---:|---:|---:|---:|---:|
| 32 MiB | dense_float32 | 3 | 38.74 | 97.08 | 32.80 | 64.88 | 64.88 |
| 32 MiB | int8_full_dequantize | 3 | 64.27 | 105.01 | 32.52 | 40.70 | 40.69 |
| 32 MiB | int8_tiled | 3 | 157.15 | 50.02 | 32.67 | 40.82 | 40.82 |
| 64 MiB | dense_float32 | 3 | 76.10 | 161.30 | 32.70 | 96.76 | 96.75 |
| 64 MiB | int8_full_dequantize | 3 | 128.11 | 177.44 | 32.59 | 48.88 | 48.87 |
| 64 MiB | int8_tiled | 3 | 246.91 | 58.17 | 32.73 | 49.05 | 49.05 |

Numerical checks: **True**; int8 tiled/full tolerance rtol=0.0001, atol=1e-05. Quantization error against dense mixing is recorded separately; this does not measure model quality.

Raw per-process phase peaks/RSS, load/persist/subprocess time, parent preparation/quantization cost, numerical errors and hashes are in probe.json and workers/. Outputs are retained in outputs/; temporary input fixtures can be regenerated from the recorded configuration and hashes.

Stable numerical/config/code SHA256: `ff533302cb5a285de903d5c7ef4fcd93d75fdee5945a17068dbe9f343fd706b9`
Full variable observation SHA256: `9cbf53df6e3c899381f4ef72c862ff45d168ba7cd11124bbe95f8dd71be3b793`

## Limits

- Synthetic random inference-only banks and one seeded shared query. No real activations, learned pseudo-query, training/backward, model quality, GPU or upstream AttnRes implementation is measured.
- Inputs are prepacked once in the parent. Worker timing excludes fixture generation, quantization, input loading and output persistence; these costs are recorded separately. This is not per-step quantization or a deployable activation/retention system.
- Every method/case/repeat uses a fresh Python process. Int8 workers load only packed values, scales and query, never the dense float bank. No memory mapping is used.
- Process peak is an OS lifetime high-water resident/working-set measurement sampled after output persistence, before final metadata serialization/exit. It includes Python/NumPy imports, input buffers, allocator behavior, temporaries and output storage; it is not precise operator-only allocation or GPU peak memory.
- Post-import and post-load high-water increments are differences between lifetime maxima, not isolated operator peaks. Freed or cached allocations, page residency, OS scheduling and system load affect observations.
- Linux uses procfs VmHWM/VmRSS in KiB converted to bytes; ru_maxrss is retained only as a diagnostic. If procfs is unavailable, the fallback ru_maxrss can contain an inherited pre-exec high-water and current RSS is unavailable. Darwin ru_maxrss uses bytes. Windows uses GetProcessMemoryInfo PeakWorkingSetSize and WorkingSetSize in bytes.
- The full-int8 path retains packed inputs and creates a complete float32 dequantized bank before the existing full_mix; construction/quantization was excluded. The tiled path makes two passes, recomputes RMSNorm/logits, and accumulates weighted sums in float64. No latency or memory improvement threshold is assumed.
- Worker order is deterministically shuffled within each shape/seed to interleave methods and repeats. This reduces simple fixed-order bias but does not control temperature, background work or OS allocator differences. At most three repeats are descriptive, not statistical performance guarantees.
- Fixture/output and code/config hashes identify numerical evidence. The stable result hash excludes timing, memory, process IDs and platform scheduling; the full observation hash includes variable measurements. Exact numerical hashes can differ across NumPy/platform versions even when tolerance checks pass.
