"""Keep the backend dependency graph acyclic and pointed inward."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

APP_ROOT = Path(__file__).parents[3] / "app"

FORBIDDEN_IMPORTS = {
    "app.api": ("app.worker",),
    "app.models": ("app.api", "app.services", "app.worker", "app.rag"),
    "app.schemas": ("app.api", "app.services", "app.worker"),
    "app.core": ("app.api", "app.worker"),
    "app.services": ("app.api", "app.worker"),
    "app.rag": ("app.api", "app.worker"),
}


def _modules() -> dict[str, Path]:
    return {
        ".".join(path.relative_to(APP_ROOT.parent).with_suffix("").parts): path
        for path in APP_ROOT.rglob("*.py")
    }


def _raw_imports(path: Path, module: str) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = resolve_name(f"{'.' * node.level}{node.module or ''}", package)
            elif node.module:
                target = node.module
            else:
                continue
            imports.append((node.lineno, target))
            imports.extend(
                (node.lineno, f"{target}.{alias.name}") for alias in node.names
            )
    return imports


def test_layers_do_not_import_outward() -> None:
    violations: list[str] = []
    for module, path in _modules().items():
        for source_prefix, blocked_prefixes in FORBIDDEN_IMPORTS.items():
            if module != source_prefix and not module.startswith(f"{source_prefix}."):
                continue
            for line, target in _raw_imports(path, module):
                if any(
                    target == blocked or target.startswith(f"{blocked}.")
                    for blocked in blocked_prefixes
                ):
                    violations.append(
                        f"{path.relative_to(APP_ROOT.parent)}:{line} -> {target}"
                    )
    assert not violations, "Layer boundary violations:\n" + "\n".join(violations)


def test_application_import_graph_is_acyclic() -> None:
    modules = _modules()
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for module, path in modules.items():
        for _, target in _raw_imports(path, module):
            candidate = target
            while candidate and candidate not in modules:
                candidate = candidate.rpartition(".")[0]
            if candidate in modules and candidate != module:
                graph[module].add(candidate)

    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            start = active.index(module)
            cycle = active[start:] + [module]
            raise AssertionError("Import cycle: " + " -> ".join(cycle))
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
