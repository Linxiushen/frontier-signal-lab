The small directory-enumeration replacement in
`scripts/prepare_transformers_scandir_runtime.py` is adapted from Hugging Face
Transformers `src/transformers/utils/import_utils.py`, PR
[44253](https://github.com/huggingface/transformers/pull/44253), commit
`652f2f7a50096f1fc65356b4e7bb1b50fe1888fc`.

Copyright 2022 The HuggingFace Team. All rights reserved.

The adapted block and the original source are licensed under Apache-2.0; see
[LICENSE](LICENSE). The backport retains the pinned 4.57.3 modular/conversion
filtering rather than adopting the upstream filtering changes. The preparation
and validation code surrounding that block is original project code under the
repository's MIT license. No full dependency/runtime is distributed here.
