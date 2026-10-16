# Accumulated-state actual AdamW update fidelity

Four actual dense warmup steps, then fixed warmed weights. Matched step4 is primary; fresh step0 is secondary.

| Seed | Context | Norm-only relL2 | Attention-preserved relL2 | Treatment cosine | Error ratio | Joint gate |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | matched_step4 | 0.215667124 | 0.00856322635 | 0.999963338 | 0.0397057568 | True |
| 11 | fresh_step0 | 0.472512991 | 0.109041819 | 0.994055224 | 0.230769992 | False |
| 29 | matched_step4 | 0.239227788 | 0.00766367188 | 0.999970635 | 0.0320350405 | True |
| 29 | fresh_step0 | 0.487394248 | 0.105082811 | 0.994478936 | 0.215601253 | False |
| 47 | matched_step4 | 0.248779972 | 0.00776333583 | 0.999969868 | 0.0312056303 | True |
| 47 | fresh_step0 | 0.496342524 | 0.109491334 | 0.994006045 | 0.220596319 | False |

Primary all-seed gate: **True**.

12 native warmup steps and18 independent clone steps passed numerical theta/m/v/t controls. All76 parameters were checked per step. CE,13norm and6actual attention scopes passed. Source audit-point weights and state remained unchanged during probes.

The three schedules overlap. Four warmup steps do not establish convergence or quality. No training-trajectory, efficiency, memory, GPU or AttnRes claim. SaveScope v0.1 remains fresh-state only.

Stable SHA256: `27f898785bb8e0c5f7460dc9670e95a03aa73cb06fcc47a39656c6bf13f337bc`
Observation SHA256: `11a8e19cc6cff92ef2dbeec3ed9dc3dd90790ca7200ae63d4f9e34b931e2288b`
