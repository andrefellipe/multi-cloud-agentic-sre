"""Fixtures for the tests of the CI helper scripts in tools/ci/."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

CI_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "ci"


@pytest.fixture(scope="session")
def citations_script() -> Path:
    """Path of tools/ci/check_req_citations.py."""
    return CI_TOOLS / "check_req_citations.py"


@pytest.fixture(scope="session")
def citations(citations_script: Path) -> ModuleType:
    """tools/ci/check_req_citations.py, loaded from its path: tools/ci/ is a script folder."""
    spec = importlib.util.spec_from_file_location("check_req_citations", citations_script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {citations_script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
