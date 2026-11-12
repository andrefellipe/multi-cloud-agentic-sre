"""Smoke test: the u1 test runner finds and imports this project (plan Step 2)."""

import tomllib
from pathlib import Path

import agents

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_req_150_agents_package_imports_with_the_project_version() -> None:
    """REQ-150.1: pytest runs through uv and imports this repository's agents package.

    The version has to match pyproject.toml and the module has to come from this
    checkout, so the test fails if another installed package named ``agents``
    shadows ours.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert agents.__version__ == pyproject["project"]["version"]
    assert Path(agents.__file__).resolve().parent == REPO_ROOT / "agents"
