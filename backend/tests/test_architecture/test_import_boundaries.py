"""Keep the backend dependency graph acyclic and pointed inward."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

APP_ROOT = Path(__file__).parents[2] / "app"

APPLICATION_OWNERS = (
    "career",
    "automation",
    "conversation",
    "files",
    "identity",
    "interviews",
    "integrations",
    "memory",
    "media",
    "usage",
    "capabilities",
    "observability",
    "platform",
    "providers",
    "maintenance",
)
FORBIDDEN_IMPORTS = {
    "app.api": ("app.worker", "app.maintenance"),
    "app.models": (
        "app.api",
        "app.worker",
        "app.rag",
        *(f"app.{name}" for name in APPLICATION_OWNERS),
    ),
    "app.schemas": (
        "app.api",
        "app.worker",
        *(f"app.{name}.application" for name in APPLICATION_OWNERS),
    ),
    "app.core": ("app.api", "app.worker"),
    "app.rag": ("app.api", "app.worker", "app.maintenance"),
    **{f"app.{name}": ("app.api", "app.worker") for name in APPLICATION_OWNERS},
}


def _modules() -> dict[str, Path]:
    assert APP_ROOT.is_dir() and (APP_ROOT / "main.py").is_file()
    return {
        ".".join(
            path.relative_to(APP_ROOT.parent).with_suffix("").parts[:-1]
            if path.name == "__init__.py"
            else path.relative_to(APP_ROOT.parent).with_suffix("").parts
        ): path
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


def test_scan_is_real_and_retired_owners_cannot_return():
    modules = _modules()
    assert {
        "app.main",
        "app.conversation",
        "app.usage.runtime",
        "app.rag.retrieval.pipeline",
    } <= modules.keys(), "architecture test must inspect the actual application"
    assert "app.conversation" in modules  # __init__ side effects count too
    assert not (APP_ROOT / "services").exists(), "no duplicate legacy service owner"
    for module, path in modules.items():
        for _, target in _raw_imports(path, module):
            assert not (target == "app.services" or target.startswith("app.services."))
            if target == "app.maintenance" or target.startswith("app.maintenance."):
                assert module.startswith("app.maintenance"), (module, target)


def test_only_application_owners_create_domain_rows():
    """HTTP handlers may own a short transaction, never a second ORM writer."""
    for path in [
        p
        for directory in ("api", "agent_runtime/tools", "worker/tasks")
        for p in (APP_ROOT / directory).rglob("*.py")
    ]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                # commit is intentionally allowed: caller-owned application UoW.
                assert not (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "db"
                    and node.func.attr in {"add", "add_all", "delete"}
                ), (
                    path,
                    node.lineno,
                    "domain mutations belong to the application owner",
                )


def test_runtime_package_assets_exist():
    assert (APP_ROOT / "providers/catalog/seed_catalog.json").is_file()
    assert list((APP_ROOT / "conversation/context_templates").glob("*.md"))
