"""List the REQ IDs of a unit that no test cites (REQ-151.1).

This is the interim citation check until u2's CI traceability report replaces it.

A test cites a requirement in its own name or its own docstring:

- in the name, as ``req_NNN``: ``test_req_032_duplicate_alert_records_once`` cites
  REQ-032;
- in the docstring, written out: ``REQ-032``, or a detailed ID such as ``REQ-151.1``.
  Detailed IDs can only be cited in the docstring.

Tests are what pytest collects by default: functions whose names start with
``test``, and such methods of classes whose names start with ``Test``, in files
named ``test_*.py`` or ``*_test.py``. Module, class and helper docstrings do not
count: the citation sits on the test that verifies the requirement.

A listed ID is cited when a test cites it or one of its detailed IDs, so a citation
of REQ-151.1 cites REQ-151. A listed detailed ID needs that ID or a deeper one:
REQ-151 alone does not cite REQ-151.1.

The requirements file lists one REQ ID per line. Blank lines and text after ``#``
are ignored.

Usage:
    python tools/ci/check_req_citations.py --requirements tests/u1/req-ids.txt tests/u1

Exit status: 0 when every listed ID is cited, 1 when some are not (each one is
printed), 2 when an input cannot be read.
"""

import argparse
import ast
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

type TestFunction = ast.FunctionDef | ast.AsyncFunctionDef

REQ_ID = re.compile(r"REQ-[0-9]{3}(?![0-9])(?:\.[0-9]+)*")
REQ_ID_ENTRY = re.compile(r"REQ-[0-9]{3}(?:\.[0-9]+)*")
NAME_CITATION = re.compile(r"(?:^|_)req_([0-9]{3})(?=_|$)", re.IGNORECASE)


class InputError(Exception):
    """An input file or path cannot be read or parsed."""


def read_requirements(path: Path) -> list[str]:
    """Return the REQ IDs listed in ``path``, in file order and without duplicates."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(f"cannot read the requirements file {path}: {error}") from error
    requirements: list[str] = []
    for number, line in enumerate(lines, start=1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        if not REQ_ID_ENTRY.fullmatch(entry):
            raise InputError(f"{path}:{number}: not a REQ ID: {entry!r}")
        if entry not in requirements:
            requirements.append(entry)
    if not requirements:
        raise InputError(f"{path} lists no REQ IDs")
    return requirements


def is_test_file(path: Path) -> bool:
    """Return whether pytest would collect tests from ``path`` by default."""
    return path.suffix == ".py" and (
        path.name.startswith("test_") or path.name.endswith("_test.py")
    )


def find_test_files(paths: Iterable[Path]) -> list[Path]:
    """Return the test files in ``paths``: each file given, and the test files in each folder."""
    test_files: set[Path] = set()
    for path in paths:
        if path.is_file():
            test_files.add(path)
        elif path.is_dir():
            test_files.update(file for file in path.rglob("*.py") if is_test_file(file))
        else:
            raise InputError(f"test path not found: {path}")
    return sorted(test_files)


def iter_tests(body: Iterable[ast.stmt]) -> Iterator[TestFunction]:
    """Yield the test functions in a module or class body, as pytest collects them."""
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                yield node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            yield from iter_tests(node.body)


def citations_of(test: TestFunction) -> set[str]:
    """Return the REQ IDs one test cites in its name and its docstring."""
    cited = {f"REQ-{digits}" for digits in NAME_CITATION.findall(test.name)}
    docstring = ast.get_docstring(test)
    if docstring:
        cited.update(REQ_ID.findall(docstring))
    return cited


def collect_citations(test_files: Iterable[Path]) -> set[str]:
    """Return every REQ ID that a test in ``test_files`` cites."""
    cited: set[str] = set()
    for test_file in test_files:
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            raise InputError(f"cannot parse {test_file}: {error}") from error
        for test in iter_tests(tree.body):
            cited |= citations_of(test)
    return cited


def is_cited(requirement: str, cited: set[str]) -> bool:
    """Return whether ``requirement``, or one of its detailed IDs, is cited."""
    return any(
        citation == requirement or citation.startswith(f"{requirement}.") for citation in cited
    )


def find_uncited(requirements: Iterable[str], cited: set[str]) -> list[str]:
    """Return the requirements no citation covers, in their listed order."""
    return [requirement for requirement in requirements if not is_cited(requirement, cited)]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return the exit status."""
    parser = argparse.ArgumentParser(
        description="List the REQ IDs of a unit that no test cites (REQ-151.1)."
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        required=True,
        metavar="FILE",
        help="file listing the unit's REQ IDs, one per line",
    )
    parser.add_argument(
        "paths",
        type=Path,
        nargs="+",
        metavar="TEST_PATH",
        help="test file, or folder searched for test_*.py and *_test.py",
    )
    args = parser.parse_args(argv)
    try:
        requirements = read_requirements(args.requirements)
        cited = collect_citations(find_test_files(args.paths))
    except InputError as error:
        print(f"check_req_citations: {error}", file=sys.stderr)
        return 2
    uncited = find_uncited(requirements, cited)
    if uncited:
        print(f"REQ IDs in {args.requirements} that no test cites (REQ-151.1):")
        for requirement in uncited:
            print(f"  {requirement}")
        return 1
    print(f"All {len(requirements)} REQ IDs in {args.requirements} are cited by a test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
