"""Fixtures for the tests of tools/build/package.py (plan Step 30).

The tests build from a small repository in a temporary folder, with an installer
that writes the kinds of file a real ``uv pip install --target`` leaves: package
code, a compiled module, wheel metadata and installation records, a ``bin/``
script with its interpreter path, a bytecode cache and uv's ``.lock`` file. No
test reaches the network; CI's ``make package`` step runs the real installer.
"""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

BUILD_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "build"

INSTALLED = {
    "pkg_a/__init__.py": b"VALUE = 1\n",
    "pkg_a/_speed.cpython-313-aarch64-linux-gnu.so": b"\x7fELF not really",
    "pkg_a-1.0.dist-info/METADATA": b"Metadata-Version: 2.4\nName: pkg-a\nVersion: 1.0\n",
    "pkg_a-1.0.dist-info/RECORD": b"pkg_a/__init__.py,sha256=x,10\n",
    "pkg_a-1.0.dist-info/INSTALLER": b"uv\n",
    "pkg_a-1.0.dist-info/REQUESTED": b"",
    "pkg_a-1.0.dist-info/direct_url.json": b"{}",
    "bin/pkg-a": b"#!/Users/someone/project/.venv/bin/python\nimport pkg_a\n",
    "pkg_a/__pycache__/__init__.cpython-313.pyc": b"\x00\x01",
    ".lock": b"",
}


@pytest.fixture(scope="session")
def package_script() -> ModuleType:
    """tools/build/package.py, loaded from its path: tools/build/ is a script folder."""
    path = BUILD_TOOLS / "package.py"
    spec = importlib.util.spec_from_file_location("build_package_script", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_install(root: Path, target: Path) -> None:
    """Write what an installation of one dependency leaves in ``target``."""
    for name, content in INSTALLED.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


@pytest.fixture
def fake_installer() -> Callable[[Path, Path], None]:
    return fake_install


@pytest.fixture
def small_repo(tmp_path: Path) -> Path:
    """A repository with the files the package is built from."""
    root = tmp_path / "repo"
    files = {
        "agents/__init__.py": '"""Agents."""\n',
        "agents/intake/handler.py": "def handler(event, context):\n    return {}\n",
        "agents/README.md": "Not shipped: only Python files are.\n",
        "pyproject.toml": '[project]\nname = "x"\n',
        "uv.lock": "version = 1\n",
        "tools/build/package.py": "# the build script\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root
