"""Auth and business handlers must share one short-lived cached DB session."""

import ast
from pathlib import Path


def test_get_db_dependency_scope_is_consistent():
    root = Path(__file__).resolve().parents[2] / "app"
    checked = 0
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Depends"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "get_db"
            ):
                continue
            scope = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "scope"),
                None,
            )
            assert isinstance(scope, ast.Constant) and scope.value == "function", (
                path,
                node.lineno,
            )
            checked += 1
    assert checked > 200
