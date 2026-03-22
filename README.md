# code-indexer

Extracts a compact structural skeleton from Python source files — imports, constants, classes, and functions with exact line numbers — reducing file size by 70–90% while preserving everything an LLM needs to navigate a codebase.

```
module doc: [1-6]
exports: Config, AuthService, process

imports: [8-13]
  dataclasses.dataclass
  typing.{List, Optional}

consts:
  MAX_RETRIES: int = 3 [17]

classes:
  @dataclass
  Config [23-28]
    host: str
    port: int = 8080
  AuthService [31-48]
    __init__(self, secret: str) [34-36]
    @staticmethod
    validate(token: str) -> bool [39-40]

fns:
  process(data: list) -> dict [68-69]

tests: [83-105]
```

## Install

```bash
uv tool install /path/to/code-indexer
```

## Usage

```bash
# index a directory, print to stdout
code-indexer src/

# save to file
code-indexer . -o index.txt

# multiple roots, exclude a folder
code-indexer src/ tests/ --exclude migrations -o index.txt

# single file
code-indexer mymodule.py
```

Built-in excludes: `__pycache__`, `.venv`, `venv`, `.git`, `.mypy_cache`, `.ruff_cache`, `build`, `dist`, `.tox`, `node_modules`.

## As a library

```python
from code_indexer import index_source, index_file, index_paths

skeleton = index_source("def hello(): pass")
skeleton = index_file("mymodule.py")
skeleton = index_paths(["src/"], exclude=["migrations"])
```

## Next Steps

- [ ] MCP server — expose `index_paths` as a tool so agents can call it directly
- [ ] Multi-language support — extend to JS/TS, Go, Rust using the same tree-sitter approach
- [ ] Port to Rust/Go for faster indexing of large monorepos
- [ ] `--output-relative` flag to show paths relative to a given root
