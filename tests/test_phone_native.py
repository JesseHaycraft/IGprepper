"""The contract between the phone app's shared code and a platform.

The two screens ask the phone for things only through `igprepper.native`.
Android's answers are in `native/android`, a pretend phone's in
`native/fake`. Whatever the shared code asks for, both have to offer, or the
app works in tests and fails on a phone, or the reverse.

The Android modules cannot be imported here, so they are read instead.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "phone" / "src" / "igprepper"
PLATFORMS = ("android", "fake")
MODULES = ("decoder", "filelist", "log", "storage", "touch", "ui")


def _asked_for() -> dict[str, set[str]]:
    """Every `module.name` the shared code uses, for each native module."""
    asked: dict[str, set[str]] = {module: set() for module in MODULES}
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        known_as: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "native":
                for alias in node.names:
                    known_as[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in known_as
            ):
                asked[known_as[node.value.id]].add(node.attr)
    return asked


def _offered(path: Path) -> set[str]:
    """The names a module defines at its top level."""
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


ASKED = _asked_for()


def test_the_shared_code_asks_something_of_every_module():
    """If this fails the scan above has stopped finding anything, and the
    tests below would pass without checking a thing."""
    assert all(ASKED[module] for module in MODULES), ASKED
    assert "pick_folder" in ASKED["storage"] and "toast" in ASKED["ui"]


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("module", MODULES)
def test_each_platform_offers_everything_the_shared_code_asks_for(platform, module):
    path = PACKAGE / "native" / platform / f"{module}.py"
    assert path.exists(), f"{platform} has no {module}"
    missing = sorted(ASKED[module] - _offered(path))
    assert not missing, f"native/{platform}/{module}.py does not offer: {missing}"


def test_the_shared_code_reaches_the_phone_only_through_native():
    """No Android import, and no reaching through a widget to Android's own
    view, anywhere outside the platform folders."""
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("from android", "import android", "from java", "jclass(",
                          "_impl.native", "MainActivity"):
            assert forbidden not in source, f"{path.name} uses {forbidden!r}"


def test_the_pretend_phone_needs_nothing_from_android():
    for path in (PACKAGE / "native" / "fake").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "java" not in source and "from android" not in source, path.name
