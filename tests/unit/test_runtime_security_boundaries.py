from __future__ import annotations

import ast
import ctypes
import sys
from pathlib import Path

import pytest


def test_runtime_source_has_single_external_process_boundary():
    subprocess_importers: set[str] = set()
    subprocess_calls: set[tuple[str, str]] = set()
    forbidden_native_parser_imports: set[tuple[str, str]] = set()
    parser_modules = {"gzip", "soundfile", "sqlite3", "tarfile", "xml"}

    for path in sorted(Path("src/museecho").rglob("*.py")):
        relative = path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.partition(".")[0]
                    if root == "subprocess":
                        subprocess_importers.add(relative)
                    if root in parser_modules:
                        forbidden_native_parser_imports.add((relative, root))
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.partition(".")[0]
                if root == "subprocess":
                    subprocess_importers.add(relative)
                if root in parser_modules:
                    forbidden_native_parser_imports.add((relative, root))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
            ):
                subprocess_calls.add((relative, node.func.attr))
                assert all(
                    keyword.arg != "shell"
                    or not isinstance(keyword.value, ast.Constant)
                    or keyword.value.value is not True
                    for keyword in node.keywords
                )

    assert subprocess_importers == {"src/museecho/analysis/decode.py"}
    assert subprocess_calls == {
        ("src/museecho/analysis/decode.py", "Popen"),
        ("src/museecho/analysis/decode.py", "run"),
    }
    assert forbidden_native_parser_imports == set()


@pytest.mark.skipif(sys.platform != "linux", reason="the production image is Linux")
def test_runtime_zlib_excludes_minizip_writer_symbol():
    runtime_zlib = ctypes.CDLL("libz.so.1")

    with pytest.raises(AttributeError):
        getattr(runtime_zlib, "zipOpenNewFileInZip4_64")
