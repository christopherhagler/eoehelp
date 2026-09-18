"""The package layout's dependency rules, checked rather than hoped for.

docs/adr/0010-code-organization.md explains the layout. These tests keep it
true: a layering rule that only lives in a document erodes one convenient
import at a time, and the first sign is usually an import cycle at startup.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

import eoehelp_api

PACKAGE = Path(eoehelp_api.__file__).parent

FOUNDATION = {"config", "observability", "db", "core"}
CLINICAL = {"symptoms", "medications", "food", "procedures"}
# Request wiring and assembly. Everything above the domains, nothing below.
APPLICATION = {"deps", "health", "main", "models"}


def _modules() -> Iterator[tuple[str, Path]]:
    for path in sorted(PACKAGE.rglob("*.py")):
        yield ".".join(path.relative_to(PACKAGE).with_suffix("").parts), path


def _imports(path: Path) -> set[str]:
    """Top-level eoehelp_api names a module imports: 'food', 'deps', and so on."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            parts = node.module.split(".")
            if parts[0] != "eoehelp_api":
                continue
            if len(parts) > 1:
                found.add(parts[1])
            else:
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "eoehelp_api" and len(parts) > 1:
                    found.add(parts[1])
    return found


def _package(module: str) -> str:
    return module.split(".")[0]


def _violations(allowed: dict[str, set[str]]) -> list[str]:
    problems = []
    for module, path in _modules():
        package = _package(module)
        if package not in allowed:
            continue
        for imported in sorted(_imports(path) - allowed[package] - {package, "__version__"}):
            problems.append(f"{module} imports {imported}")
    return problems


def test_the_foundation_depends_on_nothing_above_it() -> None:
    """config, observability, db, and core are what every domain builds on."""
    assert (
        _violations(
            {
                "config": set(),
                "observability": set(),
                "db": {"config"},
                "core": {"config", "observability", "db"},
            }
        )
        == []
    )


def test_the_audit_trail_depends_only_on_the_foundation() -> None:
    assert _violations({"audit": FOUNDATION}) == []


def test_identity_knows_nothing_of_clinical_data() -> None:
    """Research export reads the clinical side without the identity side; the
    reverse dependency is what would make that separation impossible later."""
    assert _violations({"identity": FOUNDATION | {"audit", "deps"}}) == []


def test_clinical_domains_do_not_import_each_other() -> None:
    """Each domain reads only the patient and its own tables. Views that combine
    them, such as the doctor report and the dashboards, will sit above them."""
    allowed = FOUNDATION | {"audit", "identity", "deps"}
    assert _violations(dict.fromkeys(CLINICAL, allowed)) == []


@pytest.mark.parametrize("module", ["deps", "health"])
def test_request_wiring_is_imported_only_by_routers_and_the_app(module: str) -> None:
    importers = [
        name
        for name, path in _modules()
        if module in _imports(path)
        and not name.endswith("router")
        and _package(name) not in APPLICATION
    ]
    assert importers == []


def test_routers_do_not_build_queries() -> None:
    """Queries belong to repositories, where every patient-owned statement is
    scoped by construction. A router with its own query is outside that."""
    offenders = []
    for name, path in _modules():
        if not name.endswith("router"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
                names = {alias.name for alias in node.names}
                if names & {"select", "insert", "update", "delete", "text"}:
                    offenders.append(name)
    assert offenders == []


def test_the_synthetic_generator_is_never_part_of_a_request() -> None:
    importers = [
        name
        for name, path in _modules()
        if "synthetic" in _imports(path) and _package(name) != "synthetic"
    ]
    assert importers == []
