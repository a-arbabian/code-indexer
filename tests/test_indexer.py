"""Unit tests for code-indexer. One test per atomic feature."""

import pytest
from code_indexer import index_source, index_paths
from pathlib import Path

HERE = Path(__file__).parent


def idx(src: str) -> str:
    return index_source(src)


# ── module doc ────────────────────────────────────────────────────────────────

def test_module_doc_detected():
    assert 'module doc: [1]' in idx('"""A module."""\n')

def test_module_doc_multiline():
    assert 'module doc: [1-4]' in idx('"""\nLine one.\nLine two.\n"""\n')

def test_module_doc_single_quotes():
    assert 'module doc:' in idx("'''docstring'''\n")

def test_module_doc_absent():
    assert 'module doc' not in idx('x = 1\n')

def test_module_doc_skips_leading_comments():
    src = '# copyright\n"""doc"""\n'
    assert 'module doc:' in idx(src)


# ── imports ───────────────────────────────────────────────────────────────────

def test_import_simple():
    out = idx('import os\n')
    assert 'imports:' in out
    assert '  os' in out

def test_import_dotted():
    out = idx('import os.path\n')
    assert '  os.path' in out

def test_import_from():
    out = idx('from os import path\n')
    assert '  os.path' in out

def test_import_from_multiple_merged():
    out = idx('from typing import List, Optional\n')
    assert 'typing.{List, Optional}' in out

def test_import_trie_shared_prefix():
    out = idx('import os\nimport sys\nfrom os import path\n')
    assert 'os.path' in out
    assert 'sys' in out

def test_import_aliased_uses_original_name():
    out = idx('import os as operating_system\n')
    assert 'os' in out
    assert 'operating_system' not in out

def test_import_wildcard():
    out = idx('from os import *\n')
    assert 'os.*' in out

def test_import_line_range():
    src = 'import os\nimport sys\n'
    assert 'imports: [1-2]' in idx(src)


# ── constants ─────────────────────────────────────────────────────────────────

def test_constant_allcaps():
    out = idx('MAX = 3\n')
    assert 'consts:' in out
    assert 'MAX = 3' in out

def test_constant_annotated():
    out = idx('TIMEOUT: int = 30\n')
    assert 'TIMEOUT: int = 30' in out

def test_constant_value_truncated():
    long_val = 'x' * 80
    out = idx(f'MAX = "{long_val}"\n')
    assert '...' in out

def test_constant_skips_lowercase():
    assert 'consts' not in idx('my_var = 5\n')

def test_constant_skips_mixed_case():
    assert 'consts' not in idx('MyVar = 5\n')


# ── exports (__all__) ─────────────────────────────────────────────────────────

def test_dunder_all_list():
    out = idx('__all__ = ["Foo", "bar"]\n')
    assert 'exports: Foo, bar' in out

def test_dunder_all_tuple():
    out = idx("__all__ = ('Foo',)\n")
    assert 'exports: Foo' in out

def test_dunder_all_not_a_constant():
    # __all__ should not appear in consts section
    out = idx('__all__ = ["Foo"]\n')
    assert 'consts' not in out


# ── classes ───────────────────────────────────────────────────────────────────

def test_class_name():
    assert 'MyClass' in idx('class MyClass:\n    pass\n')

def test_class_bases_shown():
    out = idx('class Child(Parent):\n    pass\n')
    assert 'Child(Parent)' in out

def test_class_methods_listed():
    src = 'class Foo:\n    def bar(self) -> int:\n        return 1\n'
    out = idx(src)
    assert 'bar(self) -> int' in out

def test_class_method_line_numbers():
    src = 'class Foo:\n    def bar(self):\n        pass\n'
    out = idx(src)
    assert '[2]' in out or '[2-3]' in out

def test_class_decorator_shown():
    src = '@mydecorator\nclass Foo:\n    pass\n'
    out = idx(src)
    assert '@mydecorator' in out
    assert 'Foo' in out

def test_class_method_decorator_shown():
    src = 'class Foo:\n    @staticmethod\n    def bar(): pass\n'
    out = idx(src)
    assert '@staticmethod' in out


# ── dataclass fields ──────────────────────────────────────────────────────────

def test_dataclass_fields_extracted():
    src = 'from dataclasses import dataclass\n@dataclass\nclass Pt:\n    x: int\n    y: int = 0\n'
    out = idx(src)
    assert 'x: int' in out
    assert 'y: int = 0' in out

def test_dataclass_field_limit():
    fields = '\n'.join(f'    f{i}: int' for i in range(10))
    src = f'@dataclass\nclass Big:\n{fields}\n'
    out = idx(src)
    assert '...' in out

def test_non_dataclass_fields_not_extracted():
    src = 'class Foo:\n    x: int = 0\n    def method(self): pass\n'
    out = idx(src)
    assert 'x: int' not in out


# ── functions ─────────────────────────────────────────────────────────────────

def test_function_name_and_params():
    out = idx('def process(data: list) -> dict:\n    pass\n')
    assert 'process(data: list) -> dict' in out

def test_function_no_return_type():
    out = idx('def run(x: int):\n    pass\n')
    assert 'run(x: int)' in out
    assert '->' not in out

def test_function_decorator_shown():
    src = '@cache\ndef compute(n: int) -> int:\n    pass\n'
    out = idx(src)
    assert '@cache' in out
    assert 'compute(n: int) -> int' in out

def test_function_line_range():
    src = 'def foo():\n    x = 1\n    return x\n'
    assert '[1-3]' in idx(src)


# ── test detection ────────────────────────────────────────────────────────────

def test_test_function_collapsed():
    src = 'def test_foo():\n    assert True\n'
    out = idx(src)
    assert 'tests:' in out
    assert 'fns:' not in out

def test_test_class_collapsed():
    src = 'class TestFoo:\n    def test_bar(self): pass\n'
    out = idx(src)
    assert 'tests:' in out
    assert 'classes:' not in out

def test_testcase_subclass_collapsed():
    src = 'import unittest\nclass MyTest(unittest.TestCase):\n    def test_x(self): pass\n'
    out = idx(src)
    assert 'tests:' in out

def test_regular_class_not_collapsed():
    src = 'class MyService:\n    def run(self): pass\n'
    out = idx(src)
    assert 'classes:' in out
    assert 'tests:' not in out

def test_test_lines_span_full_range():
    src = 'def test_a():\n    pass\n\ndef test_b():\n    pass\n'
    out = idx(src)
    assert 'tests: [1-5]' in out


# ── section ordering ──────────────────────────────────────────────────────────

def test_section_order():
    src = 'import os\nMAX = 1\nclass Foo: pass\ndef bar(): pass\n'
    out = idx(src)
    assert out.index('imports') < out.index('consts') < out.index('classes') < out.index('fns')


# ── index_paths ───────────────────────────────────────────────────────────────

def test_index_paths_single_file():
    out = index_paths([HERE / 'example.py'])
    assert 'AuthService' in out
    assert '# 1 file indexed' in out

def test_index_paths_directory():
    out = index_paths([HERE])
    assert '# ' in out  # has a header
    assert 'files indexed' in out

def test_index_paths_excludes_pattern():
    out = index_paths([HERE], exclude=['example.py'])
    assert 'AuthService' not in out

def test_index_paths_summary_line():
    out = index_paths([HERE / 'example.py'])
    assert out.strip().endswith('1 file indexed')
