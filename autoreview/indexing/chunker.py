from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from autoreview.core.schemas import CodeChunk

PY_LANGUAGE = Language(tspython.language())

CHUNK_TYPES = {"function_definition", "class_definition"}


def _get_docstring(node) -> str | None:
    body = node.child_by_field_name("body")
    if body and body.child_count > 0:
        first = body.children[0]
        if first.type == "expression_statement" and first.child_count > 0:
            expr = first.children[0]
            if expr.type == "string":
                return expr.text.decode()
    return None


def _qualified_name(node) -> str:
    """Build a dotted name by climbing the tree, collecting names only from function/class nodes."""
    parts = []
    current = node
    while current is not None:
        if current.type in CHUNK_TYPES:
            name_node = current.child_by_field_name("name")
            if name_node:
                parts.append(name_node.text.decode())
        current = current.parent
    return ".".join(reversed(parts))


def chunk_file(file_path: Path, source: str | None = None) -> list[CodeChunk]:
    """Parse a Python file and return one CodeChunk per function/class/module-block."""
    if source is None:
        source = file_path.read_text()
    source_bytes = source.encode()

    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source_bytes)

    chunks: list[CodeChunk] = []
    module_lines = set(range(len(source.splitlines())))
    file_str = str(file_path)

    def visit(node):
        if node.type in CHUNK_TYPES:
            start = node.start_point[0]
            end = node.end_point[0]
            chunks.append(CodeChunk(
                file_path=file_str,
                qualified_name=_qualified_name(node),
                kind="class" if node.type == "class_definition" else "function",
                start_line=start + 1,
                end_line=end + 1,
                content=source_bytes[node.start_byte:node.end_byte].decode(),
                docstring=_get_docstring(node),
            ))
            for line in range(start, end + 1):
                module_lines.discard(line)
            # Recurse into classes to also extract methods
            if node.type == "class_definition":
                for child in node.children:
                    visit(child)
            return

        for child in node.children:
            visit(child)

    visit(tree.root_node)

    # Whatever lines weren't inside a function/class are module-level code
    if module_lines:
        source_lines = source.splitlines()
        module_text = "\n".join(
            source_lines[i] for i in sorted(module_lines) if source_lines[i].strip()
        )
        if module_text.strip():
            sorted_lines = sorted(module_lines)
            chunks.append(CodeChunk(
                file_path=file_str,
                qualified_name="<module>",
                kind="module",
                start_line=sorted_lines[0] + 1,
                end_line=sorted_lines[-1] + 1,
                content=module_text,
            ))

    return chunks
