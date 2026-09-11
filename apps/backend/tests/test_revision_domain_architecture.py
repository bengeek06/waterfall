"""The revision domain stays pure: no ORM, no web framework, no clock, no I/O (E14-02).

Checked by walking the AST of every module of the package rather than by grepping
its text, so a mention in a comment or a docstring cannot fail the test, and a
trivially dynamic ``importlib.import_module("sqlalchemy")`` cannot slip past it.

This is an architecture rule of the EPIC, not a temporary test-bench constraint:
the tree logic stays in this pure module, and the persistence service of E14-04
only loads, delegates and writes back.

The checks themselves are exercised against deliberately crafted sources (see
``test_the_import_check_catches_*``), so that the rule is proven to bite rather
than merely to pass on code that never tried to break it.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
DOMAIN_ROOT = SRC_ROOT / "waterfall" / "domain" / "revision"

#: A module is forbidden if it *is* one of these or lives under one of them.
#: The application layers the domain must never depend on, plus every standard
#: library entry point to a clock, a file, a socket or a source of randomness --
#: the domain is a pure function of the state it is handed.
FORBIDDEN_ROOTS = (
    "sqlalchemy",
    "fastapi",
    "starlette",
    "pydantic",
    "waterfall.models",
    "waterfall.schemas",
    "waterfall.services",
    "waterfall.db",
    "waterfall.api",
    "waterfall.core",
    "time",
    "random",
    "secrets",
    "uuid",
    "os",
    "pathlib",
    "socket",
    "io",
    "subprocess",
    "requests",
    "httpx",
)

#: Dynamic import helpers whose string argument must be checked too.
_DYNAMIC_IMPORTERS = ("__import__", "import_module")

#: Implicit clock reads, whoever the owner: ``datetime.datetime.now()``,
#: ``dt.now()`` after an aliased import, ``date.today()``... A timestamp is always
#: passed in as a parameter.
_CLOCK_ATTRIBUTES = ("now", "utcnow", "today")


def _domain_modules() -> list[Path]:
    modules = sorted(DOMAIN_ROOT.rglob("*.py"))
    assert modules, f"no module found under {DOMAIN_ROOT}"
    return modules


def _package_of(module_path: Path) -> str:
    """Dotted package a module belongs to, e.g. ``waterfall.domain.revision``."""
    relative = module_path.resolve().relative_to(SRC_ROOT)
    return ".".join(relative.parts[:-1])


def _absolute_module(module: str | None, level: int, package: str) -> str:
    """Resolve an ``ImportFrom`` target, relative levels included, to a dotted name.

    ``from ... import models`` inside ``waterfall.domain.revision`` is
    ``waterfall.models``: a relative import is exactly as forbidden as the
    absolute one it is spelled differently from.
    """
    if level == 0:
        return module or ""
    parts = package.split(".")
    base = ".".join(parts[: len(parts) - (level - 1)])
    return f"{base}.{module}" if module else base


def _is_forbidden(module: str) -> bool:
    if not module:
        return False
    return any(module == root or module.startswith(f"{root}.") for root in FORBIDDEN_ROOTS)


def _imported_modules(tree: ast.AST, package: str) -> list[str]:
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_module(node.module, node.level, package)
            imported.append(base)
            # ``from ... import models`` names the package through the alias, not
            # through ``node.module``: each imported name may itself be a module.
            imported.extend(f"{base}.{alias.name}" for alias in node.names if base)
        elif isinstance(node, ast.Call):
            imported.extend(_dynamically_imported_modules(node))
    return imported


def _dynamically_imported_modules(node: ast.Call) -> list[str]:
    func = node.func
    name = (
        func.id
        if isinstance(func, ast.Name)
        else func.attr
        if isinstance(func, ast.Attribute)
        else ""
    )
    if name not in _DYNAMIC_IMPORTERS:
        return []
    return [
        argument.value
        for argument in node.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    ]


def _forbidden_imports(source: str, package: str) -> list[str]:
    tree = ast.parse(source)
    return [module for module in _imported_modules(tree, package) if _is_forbidden(module)]


def _clock_reads(source: str) -> list[str]:
    """Every ``<anything>.now/utcnow/today`` the source names, whoever the owner."""
    tree = ast.parse(source)
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in _CLOCK_ATTRIBUTES
    ]


@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda path: path.name)
def test_domain_module_imports_neither_orm_nor_web_framework_nor_io(module_path: Path) -> None:
    offenders = _forbidden_imports(
        module_path.read_text(encoding="utf-8"), _package_of(module_path)
    )

    assert not offenders, f"{module_path.name} imports {offenders}"


@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda path: path.name)
def test_domain_module_reads_no_clock(module_path: Path) -> None:
    """``now`` is always a parameter: a pure domain never reads the wall clock."""
    offenders = _clock_reads(module_path.read_text(encoding="utf-8"))

    assert not offenders, f"{module_path.name} reads a clock through {offenders}"


def test_the_whole_domain_package_is_covered_by_this_check() -> None:
    """Guards against the check silently covering nothing after a rename."""
    names = {path.name for path in _domain_modules()}

    assert "__init__.py" in names
    assert {
        "entities.py",
        "invariants.py",
        "tree.py",
        "lifecycle.py",
        "work_breakdown.py",
    } <= names


def test_the_package_of_a_domain_module_is_resolved_from_its_path() -> None:
    assert _package_of(DOMAIN_ROOT / "tree.py") == "waterfall.domain.revision"
    assert _package_of(DOMAIN_ROOT / "__init__.py") == "waterfall.domain.revision"


# --------------------------------------------------------------------------------------
# The check bites: one case per way the earlier, laxer version could be bypassed
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("absolute import", "import sqlalchemy\n"),
        ("absolute from-import", "from waterfall.models import User\n"),
        ("relative from-import of the ORM layer", "from ... import models\n"),
        ("deep relative from-import", "from ...models.resources import Role\n"),
        ("submodule import", "import sqlalchemy.orm\n"),
        ("dynamic import", "import importlib\nimportlib.import_module('sqlalchemy')\n"),
        ("clock module", "import time\ntime.time()\n"),
        ("randomness", "import random\nrandom.random()\n"),
        ("identifier generation", "import uuid\nuuid.uuid4()\n"),
        ("filesystem", "from pathlib import Path\nPath('x').read_text()\n"),
        ("environment", "import os\nos.environ['X']\n"),
        ("socket", "import socket\nsocket.socket()\n"),
        ("service layer", "from waterfall.services.planning_tree import build\n"),
        ("session layer", "from waterfall.db.session import get_db\n"),
        ("transport layer", "from waterfall.api.dependencies import get_current_active_user\n"),
    ],
)
def test_the_import_check_catches_every_known_bypass(label: str, source: str) -> None:
    offenders = _forbidden_imports(source, "waterfall.domain.revision")

    assert offenders, f"the import check lets {label} through"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("qualified module attribute", "import datetime\ndatetime.datetime.now()\n"),
        ("aliased class", "from datetime import datetime as dt\ndt.now()\n"),
        ("deprecated utcnow", "import datetime\ndatetime.datetime.utcnow()\n"),
        ("date only", "from datetime import date\ndate.today()\n"),
        ("indirection through a local", "clock = __import__('datetime')\nclock.date.today()\n"),
    ],
)
def test_the_clock_check_catches_every_known_bypass(label: str, source: str) -> None:
    offenders = _clock_reads(source)

    assert offenders, f"the clock check lets {label} through"


def test_the_checks_accept_what_the_domain_legitimately_uses() -> None:
    """No false positive on the imports the pure domain actually needs."""
    source = (
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "from datetime import date, datetime\n"
        "from decimal import Decimal\n"
        "from enum import StrEnum\n"
        "from .errors import NotFoundError\n"
        "from waterfall.domain.revision.entities import Project\n"
    )

    assert _forbidden_imports(source, "waterfall.domain.revision") == []
    assert _clock_reads(source) == []


def test_the_package_re_exports_every_operation_its_modules_expose() -> None:
    """``__all__`` *is* the boundary the service layer of E14-04 consumes.

    An operation reachable only by importing a submodule is not part of a declared
    surface, it is an accident of Python's import machinery -- so every public
    callable of the operation modules must be named here, and the facet module
    itself must be reachable under its own name.
    """
    import waterfall.domain.revision as package
    from waterfall.domain.revision import facets, tree, work_breakdown

    exposed = {
        name
        for module in (facets, tree, work_breakdown)
        for name, value in vars(module).items()
        if not name.startswith("_")
        and callable(value)
        and getattr(value, "__module__", "") == module.__name__
    }
    missing = exposed - set(package.__all__)

    assert exposed, "no operation found: the introspection no longer sees the modules"
    assert not missing, f"operations missing from the package surface: {sorted(missing)}"
    assert "facets" in package.__all__
    assert package.__all__ == sorted(package.__all__)


def test_the_domain_package_imports_cleanly_without_the_application() -> None:
    """Importing the domain in a *fresh* interpreter pulls in no ORM and no web stack.

    Run as a subprocess on purpose: inside the test process SQLAlchemy is already
    loaded by the rest of the suite, so re-importing the package there could only
    ever assert on leftovers from other modules.
    """
    script = (
        "import sys\n"
        "import waterfall.domain.revision\n"
        "leaked = sorted({name.split('.')[0] for name in sys.modules}"
        " & {'sqlalchemy', 'fastapi', 'starlette', 'pydantic'})\n"
        "assert not leaked, leaked\n"
        "assert waterfall.domain.revision.Project(id=1).work_items == {}\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
