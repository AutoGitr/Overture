"""The layering AGENTS.md describes, read from the code itself."""

lazy import ast
lazy from collections.abc import Iterator
lazy from pathlib import Path

lazy import pytest

lazy import overture

ROOT = Path(overture.__file__).parent
PACKAGE = "overture"

#: The layers each layer may import. Everything else is an inversion: a new
#: edge here is a design decision, made in review, not a side effect.
ALLOWED: dict[str, frozenset[str]] = {
    name: frozenset(allowed)
    for name, allowed in {
        "dataset_contract": (),
        "version": (),
        "runtime_paths": (),
        "passwords": (),
        "domain": ("dataset_contract",),
        "utils": ("config", "dataset_contract", "domain"),
        "config": ("domain", "passwords", "utils"),
        "db": ("domain", "utils"),
        "repositories": ("dataset_contract", "db", "domain", "utils"),
        "integrations": ("config", "dataset_contract", "domain", "schemas", "utils"),
        "schemas": (
            "dataset_contract",
            "db",
            "domain",
            "integrations",
            "jobs",
            "media_servers",
            "utils",
        ),
        "protocols": ("schemas",),
        "ws": ("jobs", "protocols", "schemas", "utils"),
        "jobs": ("db", "protocols", "schemas", "utils", "ws"),
        "media_servers": (
            "config",
            "dataset_contract",
            "domain",
            "integrations",
            "jobs",
            "schemas",
            "utils",
            "version",
        ),
        "services": (
            "config",
            "dataset_contract",
            "db",
            "domain",
            "integrations",
            "jobs",
            "media_servers",
            "passwords",
            "protocols",
            "repositories",
            "schemas",
            "utils",
            "ws",
        ),
        "routers": (
            "dependencies",
            "domain",
            "jobs",
            "schemas",
            "services",
            "utils",
            "ws",
        ),
    }.items()
}

#: The only modules that may reach the assembled application.
RUNTIME_USERS = {"overture.cli", "overture.dependencies", "overture.main"}

#: Import cycles that are deliberate: models name each other in relationships,
#: and importing the models is what registers their tables.
ALLOWED_CYCLES = (
    "overture.db.models.",
    "overture.db",
)

#: What opening or ending a transaction looks like, which only services do.
TRANSACTION_CALLS = {"read_session", "write_session", "commit", "rollback"}


def _module_name(path: Path) -> str:
    parts = path.relative_to(ROOT.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _sources() -> dict[str, tuple[Path, ast.Module]]:
    return {
        _module_name(path): (path, ast.parse(path.read_text(encoding="utf-8")))
        for path in ROOT.rglob("*.py")
        if "migrations" not in path.parts and "frontend" not in path.parts
    }


SOURCES = _sources()


def _layer(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else parts[0]


def _imports(module: str, tree: ast.Module) -> Iterator[str]:
    """Every project module *module* imports, lazily, locally or at the top."""
    is_package = SOURCES[module][0].name == "__init__.py"
    package = module.split(".") if is_package else module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (
                alias.name for alias in node.names if alias.name.startswith(PACKAGE)
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                target = ".".join([*base, *([node.module] if node.module else [])])
            else:
                target = node.module or ""
            if target.startswith(PACKAGE):
                yield target
                yield from (f"{target}.{alias.name}" for alias in node.names)


IMPORTS = {
    module: {
        target
        for target in _imports(module, tree)
        if target in SOURCES and target != module
    }
    for module, (_, tree) in SOURCES.items()
}


@pytest.mark.parametrize("layer", sorted(ALLOWED))
def test_each_layer_imports_only_what_it_may(layer: str) -> None:
    inversions = sorted(
        f"{module} -> {target}"
        for module, targets in IMPORTS.items()
        if _layer(module) == layer
        for target in targets
        if _layer(target) != layer
        and target != PACKAGE
        and _layer(target) not in ALLOWED[layer]
    )
    assert not inversions


def test_only_the_entry_points_reach_the_assembled_application() -> None:
    assert {
        module for module, targets in IMPORTS.items() if "overture.runtime" in targets
    } <= RUNTIME_USERS


@pytest.mark.parametrize("layer", ["routers", "repositories"])
def test_transactions_belong_to_services(layer: str) -> None:
    opened = sorted(
        f"{module}:{node.lineno} {node.attr}"
        for module, (_, tree) in SOURCES.items()
        if _layer(module) == layer
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in TRANSACTION_CALLS
    )
    assert not opened


def _cycles() -> list[set[str]]:
    """The strongly connected groups of modules, by Tarjan's algorithm."""
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    found: list[set[str]] = []

    def visit(module: str) -> None:
        order[module] = low[module] = len(order)
        stack.append(module)
        for target in IMPORTS[module]:
            if target not in order:
                visit(target)
                low[module] = min(low[module], low[target])
            elif target in stack:
                low[module] = min(low[module], order[target])
        if low[module] == order[module]:
            group = {stack.pop()}
            while module not in group:
                group.add(stack.pop())
            if len(group) > 1:
                found.append(group)

    for module in IMPORTS:
        if module not in order:
            visit(module)
    return found


def test_modules_import_each_other_in_one_direction() -> None:
    cycles = [
        sorted(group)
        for group in _cycles()
        if not all(module.startswith(ALLOWED_CYCLES) for module in group)
    ]
    assert not cycles
