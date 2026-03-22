"""code-indexer: extract a structural skeleton from Python source files.

Produces a compact, line-annotated summary suitable for LLM context windows.
Reduces file size by 70-90% while preserving all structural information.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from fnmatch import fnmatch
from pathlib import Path
from typing import Collection, Optional

import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser

_LANGUAGE = Language(tsp.language())
_PARSER = Parser(_LANGUAGE)

_LINE_WRAP = 120
_FIELD_LIMIT = 8
_VALUE_LIMIT = 60


# ── helpers ───────────────────────────────────────────────────────────────────

def _t(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode()

def _compact(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

def _trunc(s: str) -> str:
    return s if len(s) <= _VALUE_LIMIT else s[:_VALUE_LIMIT - 3] + '...'

def _lr(start: int, end: int) -> str:
    return f'[{start}]' if start == end else f'[{start}-{end}]'

def _find(node: Node, kind: str) -> Optional[Node]:
    return next((c for c in node.children if c.type == kind), None)


# ── data structures ───────────────────────────────────────────────────────────

class Section(IntEnum):
    IMPORT   = 0
    CONSTANT = 1
    CLASS    = 2
    FUNCTION = 3


@dataclass
class Entry:
    section:      Section
    line_start:   int
    line_end:     int
    text:         str
    children:     list[str]       = field(default_factory=list)
    attrs:        list[str]       = field(default_factory=list)
    import_paths: list[list[str]] = field(default_factory=list)  # imports only


# ── import trie ───────────────────────────────────────────────────────────────

class Trie:
    def __init__(self) -> None:
        self.kids: dict[str, Trie] = {}
        self.leaf = False

    def insert(self, path: list[str]) -> None:
        node = self
        for seg in path:
            node = node.kids.setdefault(seg, Trie())
        node.leaf = True

    def render(self) -> list[str]:
        return _render_kids(self.kids)


def _render_node(seg: str, node: Trie) -> list[str]:
    if not node.kids:
        return [seg]
    sub = _render_kids(node.kids)
    if node.leaf:
        return [seg] + [f'{seg}.{s}' for s in sub]
    if len(sub) == 1:
        return [f'{seg}.{sub[0]}']
    return [f'{seg}.{{{", ".join(sub)}}}']


def _render_kids(kids: dict[str, Trie]) -> list[str]:
    out: list[str] = []
    for seg, node in sorted(kids.items()):
        out.extend(_render_node(seg, node))
    return out


# ── extraction ────────────────────────────────────────────────────────────────

def _import_paths(node: Node, src: bytes) -> list[list[str]]:
    paths: list[list[str]] = []

    if node.type == 'import_statement':
        for child in node.named_children:
            name_node = child.child_by_field_name('name') if child.type == 'aliased_import' else child
            if name_node:
                paths.append(_t(name_node, src).split('.'))
    else:  # import_from_statement
        mod = node.child_by_field_name('module_name')
        base = _t(mod, src).split('.') if mod else []
        mod_range = (mod.start_byte, mod.end_byte) if mod else None
        for child in node.named_children:
            if mod_range and (child.start_byte, child.end_byte) == mod_range:
                continue
            if child.type == 'aliased_import':
                name_node = child.child_by_field_name('name')
                if name_node:
                    paths.append(base + [_t(name_node, src)])
            elif child.type == 'wildcard_import':
                paths.append(base + ['*'])
            elif child.type in ('dotted_name', 'identifier'):
                paths.append(base + [_t(child, src)])

    return paths


def _fn_sig(node: Node, src: bytes) -> str:
    name   = node.child_by_field_name('name')
    params = node.child_by_field_name('parameters')
    ret    = node.child_by_field_name('return_type')
    n = _t(name, src) if name else '?'
    p = _compact(_t(params, src)) if params else '()'
    r = f' -> {_t(ret, src)}' if ret else ''
    return f'{n}{p}{r}'


def _class_entry(node: Node, src: bytes, decs: list[str]) -> tuple[Entry, bool]:
    name_node = node.child_by_field_name('name')
    name = _t(name_node, src) if name_node else '?'

    arg_node = _find(node, 'argument_list')
    bases = [_t(c, src) for c in (arg_node.named_children if arg_node else [])
             if c.type in ('identifier', 'attribute')]
    bases_str = f'({", ".join(bases)})' if bases else ''

    is_dataclass = any('@dataclass' in d for d in decs)
    body = node.child_by_field_name('body')
    children: list[str] = []

    if body:
        if is_dataclass:
            dc_fields: list[str] = []
            for child in body.named_children:
                if child.type == 'expression_statement':
                    inner = child.named_children[0] if child.named_children else None
                    # annotated assignment: name: type [= value]
                    if inner and inner.type == 'assignment' and inner.child_by_field_name('type'):
                        dc_fields.append(_compact(_t(inner, src)))
            if len(dc_fields) > _FIELD_LIMIT:
                dc_fields = dc_fields[:_FIELD_LIMIT] + ['...']
            children.extend(dc_fields)

        for child in body.named_children:
            child_decs: list[str] = []
            fn_node: Optional[Node] = None

            if child.type == 'function_definition':
                fn_node = child
            elif child.type == 'decorated_definition':
                for c in child.children:
                    if c.type == 'decorator':
                        child_decs.append(_t(c, src))
                    elif c.type == 'function_definition':
                        fn_node = c

            if fn_node:
                sig = _fn_sig(fn_node, src)
                lr = _lr(fn_node.start_point[0] + 1, fn_node.end_point[0] + 1)
                children.extend(child_decs)
                children.append(f'{sig} {lr}')

    is_test_cls = (
        name.startswith('Test') or name.endswith(('Test', 'Tests'))
        or any(b in ('TestCase', 'unittest.TestCase') for b in bases)
    )
    line_start = node.start_point[0] + 1
    line_end   = node.end_point[0] + 1
    entry = Entry(Section.CLASS, line_start, line_end, f'{name}{bases_str}',
                   children=children, attrs=decs)
    return entry, is_test_cls


def _fn_entry(node: Node, src: bytes, decs: list[str], outer_row: int | None = None) -> Entry:
    sig   = _fn_sig(node, src)
    start = (outer_row if outer_row is not None else node.start_point[0]) + 1
    end   = node.end_point[0] + 1
    return Entry(Section.FUNCTION, start, end, sig, attrs=decs)


def _const_entry(node: Node, src: bytes) -> Optional[Entry]:
    left  = node.child_by_field_name('left')
    right = node.child_by_field_name('right')
    typ   = node.child_by_field_name('type')

    if not left or left.type != 'identifier':
        return None
    name = _t(left, src)
    if not re.match(r'^[A-Z][A-Z0-9_]*$', name):
        return None

    type_str = f': {_t(typ, src)}' if typ else ''
    val_str  = f' = {_trunc(_t(right, src))}' if right else ''
    start = node.start_point[0] + 1
    end   = node.end_point[0] + 1
    return Entry(Section.CONSTANT, start, end, f'{name}{type_str}{val_str}')


def _dunder_all(node: Node, src: bytes) -> Optional[list[str]]:
    left  = node.child_by_field_name('left')
    right = node.child_by_field_name('right')
    if not left or _t(left, src) != '__all__':
        return None
    if not right or right.type not in ('list', 'tuple'):
        return None
    names: list[str] = []
    for s in right.named_children:
        if s.type == 'string':
            content = next((c for c in s.named_children if c.type == 'string_content'), None)
            if content:
                names.append(_t(content, src))
    return names or None


def _module_doc(root: Node, src: bytes) -> Optional[tuple[int, int]]:
    for child in root.named_children:
        if child.type == 'comment':
            continue
        if child.type == 'expression_statement':
            inner = child.named_children[0] if child.named_children else None
            if inner and inner.type == 'string':
                raw = _t(inner, src)
                if raw.startswith(('"""', "'''")):
                    return child.start_point[0] + 1, child.end_point[0] + 1
        break
    return None


# ── formatting ────────────────────────────────────────────────────────────────

def _format(
    entries:    list[Entry],
    module_doc: Optional[tuple[int, int]],
    exports:    Optional[list[str]],
    test_lines: list[int],
) -> str:
    out = ''

    if module_doc:
        out += f'module doc: {_lr(*module_doc)}\n'
    if exports:
        out += f'exports: {", ".join(exports)}\n'

    grouped: dict[Section, list[Entry]] = defaultdict(list)
    for e in entries:
        grouped[e.section].append(e)

    for section in sorted(grouped):
        items = grouped[section]
        sep = '\n' if out else ''

        if section == Section.IMPORT:
            min_l = min(e.line_start for e in items)
            max_l = max(e.line_end for e in items)
            trie = Trie()
            for e in items:
                for path in e.import_paths:
                    trie.insert(path)
            out += f'{sep}imports: {_lr(min_l, max_l)}\n'
            for line in trie.render():
                out += f'  {line}\n'

        elif section == Section.CONSTANT:
            out += f'{sep}consts:\n'
            for e in items:
                out += f'  {e.text} {_lr(e.line_start, e.line_end)}\n'

        elif section == Section.CLASS:
            out += f'{sep}classes:\n'
            for e in items:
                for attr in e.attrs:
                    out += f'  {attr}\n'
                out += f'  {e.text} {_lr(e.line_start, e.line_end)}\n'
                for child in e.children:
                    out += f'    {child}\n'

        elif section == Section.FUNCTION:
            out += f'{sep}fns:\n'
            for e in items:
                for attr in e.attrs:
                    out += f'  {attr}\n'
                out += f'  {e.text} {_lr(e.line_start, e.line_end)}\n'

    if test_lines:
        sep = '\n' if out else ''
        out += f'{sep}tests: {_lr(min(test_lines), max(test_lines))}\n'

    return out


# ── public API ────────────────────────────────────────────────────────────────

def index_source(source: str) -> str:
    """Return a skeleton string for the given Python source code."""
    src  = source.encode()
    root = _PARSER.parse(src).root_node

    module_doc  = _module_doc(root, src)
    entries:    list[Entry]        = []
    exports:    Optional[list[str]] = None
    test_lines: list[int]           = []

    def add(e: Entry, is_test: bool = False) -> None:
        if is_test:
            test_lines.extend(range(e.line_start, e.line_end + 1))
        else:
            entries.append(e)

    for node in root.named_children:
        match node.type:
            case 'import_statement' | 'import_from_statement':
                paths = _import_paths(node, src)
                if paths:
                    s, e_l = node.start_point[0] + 1, node.end_point[0] + 1
                    entries.append(Entry(Section.IMPORT, s, e_l, '', import_paths=paths))

            case 'class_definition':
                entry, is_test = _class_entry(node, src, [])
                add(entry, is_test)

            case 'function_definition':
                name = node.child_by_field_name('name')
                is_test = name is not None and _t(name, src).startswith('test_')
                add(_fn_entry(node, src, []), is_test)

            case 'decorated_definition':
                decs: list[str] = []
                inner: Optional[Node] = None
                for c in node.children:
                    if c.type == 'decorator':
                        decs.append(_t(c, src))
                    elif c.type in ('class_definition', 'function_definition'):
                        inner = c
                if inner:
                    outer_row = node.start_point[0]
                    if inner.type == 'class_definition':
                        entry, is_test = _class_entry(inner, src, decs)
                        entry.line_start = outer_row + 1
                        add(entry, is_test)
                    else:
                        name = inner.child_by_field_name('name')
                        is_test = name is not None and _t(name, src).startswith('test_')
                        add(_fn_entry(inner, src, decs, outer_row), is_test)

            case 'expression_statement':
                inner_node = node.named_children[0] if node.named_children else None
                if inner_node and inner_node.type == 'assignment':
                    exp = _dunder_all(inner_node, src)
                    if exp is not None:
                        exports = exp
                    else:
                        e = _const_entry(inner_node, src)
                        if e:
                            entries.append(e)

    return _format(entries, module_doc, exports, test_lines)


def index_file(path: str | Path) -> str:
    """Return a skeleton string for the given Python file."""
    p = Path(path)
    if p.suffix != '.py':
        raise ValueError(f'Expected a .py file, got: {p}')
    return index_source(p.read_text(encoding='utf-8'))


_DEFAULT_EXCLUDES = {
    '__pycache__', '.venv', 'venv', '.git', '.mypy_cache', '.ruff_cache',
    'build', 'dist', '.tox', 'node_modules',
}


def _collect_files(paths: list[Path], excluded: set[str]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        candidates = sorted(p.rglob('*.py')) if p.is_dir() else ([p] if p.suffix == '.py' else [])
        for f in candidates:
            f = f.resolve()
            if f in seen:
                continue
            if any(fnmatch(part, pat) for part in f.parts for pat in excluded):
                continue
            seen.add(f)
            result.append(f)
    return result


def index_paths(
    paths: list[str | Path],
    exclude: Collection[str] | None = None,
) -> str:
    """Index all .py files under the given files/directories, returning a single string."""
    excluded = _DEFAULT_EXCLUDES | set(exclude or [])
    py_files = _collect_files([Path(p) for p in paths], excluded)

    chunks: list[str] = []
    for f in py_files:
        skeleton = index_file(f)
        if skeleton.strip():
            chunks.append(f'# {f}\n{skeleton}')

    n = len(chunks)
    summary = f'# {n} file{"s" if n != 1 else ""} indexed'
    return ('\n'.join(chunks) + '\n' + summary + '\n') if chunks else (summary + '\n')
