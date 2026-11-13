"""Tests of tools/build/package.py (plan Step 30): the reproducible functions package."""

import hashlib
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

EPOCH = int(datetime(2026, 11, 12, 23, 0, tzinfo=UTC).timestamp())
Installer = Callable[[Path, Path], None]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_req_112_two_builds_of_the_same_sources_are_identical_and_named_after_them(
    package_script: ModuleType, small_repo: Path, fake_installer: Installer, tmp_path: Path
) -> None:
    """REQ-112.1: the package is reproducible, and named after the hash of its sources.

    Two builds of the same sources give the same bytes and the same manifest. The
    source hash is the SHA-256 over "<path> <file sha256>" lines, the formula
    infra/aws/permanent/functions.tf repeats; a code change makes a new package and
    removes the old one, and a file that is not shipped changes nothing.
    """
    first = package_script.build_package(small_repo, tmp_path / "one", fake_installer, EPOCH)
    second = package_script.build_package(small_repo, tmp_path / "two", fake_installer, EPOCH)

    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    assert first.manifest == second.manifest == first.manifest_path.read_text(encoding="utf-8")
    sources = [
        "agents/__init__.py",
        "agents/intake/handler.py",
        "pyproject.toml",
        "tools/build/package.py",
        "uv.lock",
    ]
    lines = [f"{name} {sha256((small_repo / name).read_bytes())}" for name in sources]
    assert first.source_hash == sha256("\n".join(lines).encode())
    assert first.zip_path.name == f"functions-{first.source_hash}.zip"

    (small_repo / "agents" / "README.md").write_text(
        "Edited, and still not shipped.\n", encoding="utf-8"
    )
    assert package_script.source_hash(small_repo) == first.source_hash
    (small_repo / "agents" / "intake" / "handler.py").write_text(
        "def handler(e, c):\n    return {1: 1}\n"
    )
    third = package_script.build_package(small_repo, tmp_path / "one", fake_installer, EPOCH)

    assert third.source_hash != first.source_hash
    assert sorted(path.name for path in (tmp_path / "one").iterdir()) == [
        f"functions-{third.source_hash}.manifest.txt",
        f"functions-{third.source_hash}.zip",
    ]


def test_req_112_package_holds_code_and_locked_dependencies_and_leaves_out_machine_files(
    package_script: ModuleType,
    small_repo: Path,
    fake_installer: Installer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-112.1: the package holds the code and the dependencies, and nothing machine-made.

    Entries are sorted, all stamped with the commit time, readable by everyone
    and executable only for compiled modules. bin/ scripts, bytecode caches and
    installation records are left out. The script prints the manifest and its
    hash; a failed installation fails the build and leaves no half-built files.
    """
    built = package_script.build_package(small_repo, tmp_path / "out", fake_installer, EPOCH)

    with zipfile.ZipFile(built.zip_path) as archive:
        infos = archive.infolist()
        contents = {info.filename: archive.read(info) for info in infos}
    names = [info.filename for info in infos]
    assert names == [
        "agents/__init__.py",
        "agents/intake/handler.py",
        "pkg_a-1.0.dist-info/METADATA",
        "pkg_a/__init__.py",
        "pkg_a/_speed.cpython-313-aarch64-linux-gnu.so",
    ]
    assert {info.date_time for info in infos} == {(2026, 11, 12, 23, 0, 0)}
    modes = {info.filename: (info.external_attr >> 16) & 0o777 for info in infos}
    assert modes == {name: 0o755 if ".so" in name else 0o644 for name in names}
    assert built.manifest == "".join(f"{sha256(contents[name])}  {name}\n" for name in names)

    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    assert package_script.commit_epoch(small_repo) == EPOCH
    printed = tmp_path / "printed"
    arguments = ["--output-dir", str(printed), "--repo-root", str(small_repo)]
    assert package_script.main(arguments, install=fake_installer) == 0
    out = capsys.readouterr().out
    assert out.startswith(built.manifest)
    assert f"manifest sha256 {sha256(built.manifest.encode())}" in out

    def failing_install(root: Path, target: Path) -> None:
        raise package_script.PackageError("uv pip install failed: no wheel for aarch64")

    failed = tmp_path / "failed"
    assert (
        package_script.main(
            ["--output-dir", str(failed), "--repo-root", str(small_repo)], install=failing_install
        )
        == 1
    )
    assert "package: uv pip install failed: no wheel for aarch64" in capsys.readouterr().err
    assert list(failed.iterdir()) == []

    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    assert package_script.commit_epoch(package_script.REPO_ROOT) > 1_700_000_000
