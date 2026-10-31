"""Scanner semantics only: no ML imports, training or timeout acceptance."""
import ast
from functools import lru_cache
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_transformers_scandir_runtime as prep


def scanner(source):
    tree = ast.parse(source)
    selected = [node for node in tree.body
                if (isinstance(node, ast.FunctionDef) and node.name in
                    ("fetch__all__", "create_import_structure_from_path"))
                or (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id == "BASE_FILE_REQUIREMENTS" for target in node.targets))]
    if len(selected) != 3:
        raise ValueError("Expected three reviewed scanner definitions")
    namespace = {"os": os, "lru_cache": lru_cache}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<reviewed-scanner>", "exec"), namespace)
    return namespace["create_import_structure_from_path"]


class TransformersScandirBackportTest(unittest.TestCase):
    def test_patch_refuses_unreviewed_or_already_patched_bytes(self):
        for raw in (b"", prep.OLD.encode(), prep.NEW.encode()):
            with self.assertRaises(ValueError):
                prep.patch_source(raw)

    def test_disjoint_new_destination_and_bounded_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for target in (root, root / "child", root.parent):
                with self.assertRaises(ValueError):
                    prep.prepare(root, target)
            (root / "one.py").write_bytes(b"x")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "ignored.pyc").write_bytes(b"generated")
            self.assertEqual(len(prep.inventory(root)), 2)
            with patch.object(prep, "MAX_BYTES", 0):
                with self.assertRaises(ValueError):
                    prep.inventory(root)

    def test_native_scanner_preserves_backend_filtering_and_nested_exports(self):
        # Use the exact reviewed installed source when available. CI has no ML
        # environment; this is explicitly optional rather than a fabricated run.
        root = Path(__file__).resolve().parents[1]
        path = root / "local-state/activation-venv" / prep.RELATIVE_SOURCE
        if not path.is_file():
            self.skipTest("Reviewed local dependency source unavailable")
        raw = path.read_bytes()
        old, new = scanner(raw), scanner(prep.patch_source(raw))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            files = {"__init__.py": '__all__ = ["ExcludedInit"]',
                     "configuration_fixture.py": '__all__ = ["FixtureConfig"]',
                     "modeling_fixture.py": '__all__ = ["FixtureModel"]',
                     "modeling_tf_fixture.py": '__all__ = ["TFFixtureModel"]',
                     "modular_fixture.py": '__all__ = ["ExcludedModular"]',
                     "convert_fixture.py": '__all__ = ["OriginalConversionExport"]',
                     "tokenization_fixture_fast.py": '__all__ = ["FastTokenizer"]',
                     "nested/configuration_nested.py": '__all__ = ["NestedConfig"]',
                     "__pycache__/modeling_ignored.py": '__all__ = ["IgnoredCache"]'}
            for name, text in files.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            expected = old(str(directory))
            self.assertEqual(new(str(directory)), expected)
            self.assertEqual(expected[frozenset({"torch"})]["modeling_fixture"], {"FixtureModel"})
            self.assertEqual(expected[frozenset()]["convert_fixture"], {"OriginalConversionExport"})
            self.assertNotIn("modular_fixture", expected[frozenset()])
            self.assertNotIn("__pycache__", expected)
            # Old implementation stats files twice. The replacement must use
            # DirEntry metadata rather than that redundant path API.
            new.cache_clear()
            with patch.object(os.path, "isdir", side_effect=AssertionError("redundant path stat")):
                self.assertEqual(new(str(directory)), expected)


if __name__ == "__main__":
    unittest.main()
