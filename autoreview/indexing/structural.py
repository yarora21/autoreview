from __future__ import annotations

import ast
from pathlib import Path


class StructuralIndex:
    """
    Tracks two things across a codebase:
    - call_graph:   function_name -> set of function names it calls
    - import_index: file_path     -> set of imported names
    """

    def __init__(self):
        self.call_graph: dict[str, set[str]] = {}
        self.import_index: dict[str, set[str]] = {}

    def index_file(self, file_path: Path) -> None:
        source = file_path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        file_str = str(file_path)
        imports: set[str] = set()

        for node in ast.walk(tree):
            # Collect imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.add(f"{module}.{alias.name}")

            # Collect calls made inside each function
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls: set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        name = _call_name(child)
                        if name:
                            calls.add(name)
                self.call_graph[node.name] = calls

        self.import_index[file_str] = imports

    def callers_of(self, func_name: str) -> list[str]:
        """Return all functions that call func_name."""
        return [fn for fn, calls in self.call_graph.items() if func_name in calls]

    def imports_of(self, file_path: str) -> set[str]:
        return self.import_index.get(file_path, set())


def _call_name(node: ast.Call) -> str | None:
    """Extract a readable name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def build_index(repo_path: Path) -> StructuralIndex:
    """Walk all .py files in a repo and build the structural index."""
    index = StructuralIndex()
    for py_file in repo_path.rglob("*.py"):
        index.index_file(py_file)
    return index
