# Short training histories and common-anchor actual AdamW update fidelity

Two independent eight-step histories per schedule; three clone policies at steps 4 and 8. All twelve anchors must pass the unchanged joint gate.

| Seed | History | Step | Norm-only relL2 | Treatment relL2 | Treatment cosine | Error ratio | Joint gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 101 | dense | 4 | 0.327691914 | 0.01437935 | 0.999896615 | 0.0438806982 | True |
| 101 | dense | 8 | 0.276674214 | 0.015637556 | 0.999877734 | 0.056519745 | True |
| 101 | model_except_norm_attention_saved_int8 | 4 | 0.321173448 | 0.0146071101 | 0.999893319 | 0.0454804411 | True |
| 101 | model_except_norm_attention_saved_int8 | 8 | 0.284418117 | 0.0152244056 | 0.999884111 | 0.0535282552 | True |
| 211 | dense | 4 | 0.291031347 | 0.0142971872 | 0.999897795 | 0.0491259355 | True |
| 211 | dense | 8 | 0.305398394 | 0.0149992786 | 0.999887516 | 0.0491138095 | True |
| 211 | model_except_norm_attention_saved_int8 | 4 | 0.329219147 | 0.0144742118 | 0.99989525 | 0.0439652793 | True |
| 211 | model_except_norm_attention_saved_int8 | 8 | 0.342516843 | 0.0154546576 | 0.999880577 | 0.0451208689 | True |
| 307 | dense | 4 | 0.260202528 | 0.0136694458 | 0.99990658 | 0.0525338701 | True |
| 307 | dense | 8 | 0.231534634 | 0.0142031437 | 0.999899136 | 0.0613434953 | True |
| 307 | model_except_norm_attention_saved_int8 | 4 | 0.255960548 | 0.0133461609 | 0.99991095 | 0.0521414764 | True |
| 307 | model_except_norm_attention_saved_int8 | 8 | 0.20397311 | 0.014210343 | 0.999899035 | 0.0696677273 | True |

Primary all-anchor gate: **True**.

48 actual history steps and 36 discarded clone steps use numerical theta/m/v/t controls on all 76 parameter tensors. Audit source states remain unchanged and probe gradients are cleared before history resumes.

Trajectory drift is descriptive, without a pass threshold. It mixes parameter, gradient, moment and history effects. These short synthetic trajectories provide no convergence, quality, efficiency, GPU, practical compression benefit, AttnRes or private-roadmap evidence. SaveScope v0.1 remains fresh-state only.

Stable SHA256: `c5ae6bbb167189ffe51248258257dc9ed88504e7eed54ce6da2002321c5c80cc`
Observation SHA256: `40c002a4d9f1d30e4410cb7efadf3fa7f545a58274942e9267cba86e09cfc282`
