"""Tests for tools/ci/check_req_citations.py, the interim REQ citation check (REQ-151.1)."""

import runpy
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


def write(path: Path, text: str) -> Path:
    """Write the dedented ``text`` to ``path``, creating its folder, and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def run_check(citations: ModuleType, argv: list[str]) -> int:
    """Run the check's main() and return the exit status a shell would see."""
    try:
        status = citations.main(argv)
    except SystemExit as exit_:  # argparse exits on a usage error
        return exit_.code if isinstance(exit_.code, int) else 1
    return int(status)


def test_req_151_cites_by_test_name_and_by_test_docstring(
    citations: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """REQ-151.1: ``req_NNN`` in a test's name and a REQ ID in its docstring both cite."""
    write(
        tmp_path / "tests" / "test_alerts.py",
        '''
        def test_req_032_duplicate_alert_records_once():
            pass


        class TestLedger:
            async def test_second_alert_attaches(self):
                """REQ-031: a second alert for the service attaches to the open incident."""
        ''',
    )
    requirements = write(tmp_path / "req-ids.txt", "REQ-031\nREQ-032\n")

    status = run_check(citations, ["--requirements", str(requirements), str(tmp_path / "tests")])

    assert status == 0
    assert "All 2 REQ IDs" in capsys.readouterr().out


def test_req_151_a_detailed_citation_covers_its_parent(
    citations: ModuleType, tmp_path: Path
) -> None:
    """REQ-151.1: citing REQ-151.1 cites REQ-151 too, in *_test.py files in subfolders."""
    write(
        tmp_path / "tests" / "ci" / "checks_test.py",
        '''
        def test_lists_uncited_ids():
            """Verifies REQ-151.1."""
        ''',
    )
    requirements = write(tmp_path / "req-ids.txt", "REQ-151\nREQ-151.1\n")

    status = run_check(citations, ["--requirements", str(requirements), str(tmp_path / "tests")])

    assert status == 0


def test_req_151_a_parent_citation_does_not_cover_a_detailed_id(
    citations: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """REQ-151.1: REQ-150 and REQ-150.10 are cited, so REQ-150.1 is still not.

    The test file is passed by its own path rather than its folder.
    """
    test_file = write(
        tmp_path / "tests" / "test_quality.py",
        '''
        def test_req_150_runs_ruff():
            """Also covers REQ-150.10."""
        ''',
    )
    requirements = write(tmp_path / "req-ids.txt", "REQ-150\nREQ-150.1\n")

    status = run_check(citations, ["--requirements", str(requirements), str(test_file)])

    assert status == 1
    assert capsys.readouterr().out.splitlines()[1:] == ["  REQ-150.1"]


def test_req_151_run_as_a_script_lists_uncited_ids_in_order_and_exits_1(
    citations_script: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-151.1: as CI runs it, the check prints each uncited ID once, in list order."""
    tests = tmp_path / "tests"
    write(tests / "test_intake.py", "def test_req_030_alert_creates_incident():\n    pass\n")
    requirements = write(
        tmp_path / "req-ids.txt",
        """
        # u1 intake
        REQ-035  # severity threshold

        REQ-030
        REQ-033
        REQ-035
        """,
    )
    monkeypatch.setattr(
        sys, "argv", ["check_req_citations.py", "--requirements", str(requirements), str(tests)]
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(citations_script), run_name="__main__")

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.splitlines()[1:] == ["  REQ-035", "  REQ-033"]


def test_req_151_only_tests_that_pytest_collects_can_cite(
    citations: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """REQ-151.1: module, helper and non-test-class code, and non-test files, cite nothing."""
    write(
        tmp_path / "tests" / "test_ledger.py",
        '''
        """Covers REQ-040."""


        def helper_req_041():
            """REQ-042."""


        class Helpers:
            def test_req_043_is_not_collected(self):
                pass


        def test_req_0450_is_not_a_three_digit_citation():
            pass
        ''',
    )
    write(tmp_path / "tests" / "fixtures.py", "def test_req_044_in_a_skipped_file():\n    pass\n")
    requirements = write(
        tmp_path / "req-ids.txt", "REQ-040\nREQ-041\nREQ-042\nREQ-043\nREQ-044\nREQ-045\n"
    )

    status = run_check(citations, ["--requirements", str(requirements), str(tmp_path / "tests")])

    assert status == 1
    uncited = [line.strip() for line in capsys.readouterr().out.splitlines()[1:]]
    assert uncited == ["REQ-040", "REQ-041", "REQ-042", "REQ-043", "REQ-044", "REQ-045"]


def bad_entry(root: Path) -> list[str]:
    requirements = write(root / "req-ids.txt", "REQ-151\nUS2.6\n")
    return ["--requirements", str(requirements), str(root / "tests")]


def empty_list(root: Path) -> list[str]:
    requirements = write(root / "req-ids.txt", "# nothing listed yet\n\n")
    return ["--requirements", str(requirements), str(root / "tests")]


def missing_requirements(root: Path) -> list[str]:
    return ["--requirements", str(root / "absent.txt"), str(root / "tests")]


def missing_test_path(root: Path) -> list[str]:
    requirements = write(root / "req-ids.txt", "REQ-151\n")
    return ["--requirements", str(requirements), str(root / "absent")]


def unparsable_test_file(root: Path) -> list[str]:
    requirements = write(root / "req-ids.txt", "REQ-151\n")
    write(root / "tests" / "test_broken.py", "def test_req_151_broken(:\n    pass\n")
    return ["--requirements", str(requirements), str(root / "tests")]


def no_requirements_option(root: Path) -> list[str]:
    return [str(root / "tests")]


@pytest.mark.parametrize(
    ("make_argv", "message"),
    [
        (bad_entry, "not a REQ ID: 'US2.6'"),
        (empty_list, "lists no REQ IDs"),
        (missing_requirements, "cannot read the requirements file"),
        (missing_test_path, "test path not found"),
        (unparsable_test_file, "cannot parse"),
        (no_requirements_option, "--requirements"),
    ],
)
def test_req_151_input_it_cannot_trust_exits_2(
    make_argv: Callable[[Path], list[str]],
    message: str,
    citations: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-151.1: a bad list, a missing path or an unparsable test fails loudly with 2."""
    write(tmp_path / "tests" / "test_ok.py", "def test_req_151_ok():\n    pass\n")

    status = run_check(citations, make_argv(tmp_path))

    assert status == 2
    assert message in capsys.readouterr().err
