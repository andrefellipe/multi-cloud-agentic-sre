#!/usr/bin/env python3
"""Build the Lambda functions' package reproducibly (plan Step 29, ``cicd-pipeline.md``).

The intake and the notifier run from one package: the repository's ``agents``
package, plus the runtime dependencies that ``uv.lock`` pins, built for Lambda's
Python 3.13 on arm64. ``make package`` runs this script. CI's python-quality job
runs it on every pull request and on ``main``, and prints the manifest; you
compare it with your own before you apply. Nothing is uploaded.

What makes two builds of the same commit identical:

- the dependencies come from ``uv.lock`` through ``uv export``, with every hash
  required, as wheels for ``manylinux_2_34`` on aarch64 (Lambda's Amazon Linux
  2023), never built from source;
- the archive lists its files in sorted order, with fixed permissions and one
  timestamp, the commit time (``git log -1 --format=%ct``) or ``SOURCE_DATE_EPOCH``;
- what depends on the machine that installs is left out: ``bin/`` scripts with
  their interpreter paths, bytecode caches, uv's ``.lock`` file, and each
  wheel's installation records (``RECORD``, ``INSTALLER``, ``REQUESTED``,
  ``direct_url.json``).

The package is named after the hash of its sources,
``build/lambda/functions-<source hash>.zip``. The source hash covers
``agents/**/*.py``, ``pyproject.toml``, ``uv.lock`` and this file, and
``infra/aws/permanent/functions.tf`` computes the same one. So after the sources
change, ``terraform apply`` fails until the matching package is built, instead
of deploying an old one, and CI can plan without a package.

Beside the zip it writes ``functions-<source hash>.manifest.txt``: one line per
file, ``<sha256>  <path>``. It prints the manifest, then a summary with the
manifest's own SHA-256, the line to compare. Older packages in the folder are
removed.

Usage:
    uv run python tools/build/package.py [--output-dir DIR]

Exit status: 0 when the package is built, 1 when a step fails, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
PYTHON_VERSION: Final = "3.13"
PLATFORM: Final = "aarch64-manylinux_2_34"
SOURCE_FILES: Final = ("pyproject.toml", "tools/build/package.py", "uv.lock")
LEFT_OUT_RECORDS: Final = frozenset({"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"})
ZIP_EPOCH: Final = 315_532_800
"""1980-01-01T00:00:00Z: a zip archive cannot hold an earlier time."""

Installer = Callable[[Path, Path], None]
"""Installs the locked runtime dependencies: (repository root, target folder)."""


class PackageError(Exception):
    """A step of the build failed; the message says which."""


@dataclass(frozen=True)
class Package:
    zip_path: Path
    manifest_path: Path
    source_hash: str
    manifest: str
    file_count: int


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(root: Path) -> list[str]:
    """The files the package is built from, as repository-relative paths, sorted."""
    files = {
        path.relative_to(root).as_posix()
        for path in (root / "agents").rglob("*.py")
        if path.is_file()
    }
    files.update(SOURCE_FILES)
    return sorted(files)


def source_hash(root: Path) -> str:
    """The SHA-256 over ``<path> <file sha256>`` lines, one per source file, joined by newlines.

    ``infra/aws/permanent/functions.tf`` computes the same value for the
    functions' ``source_code_hash`` and package name; keep the two in step.
    """
    lines = [f"{name} {file_sha256(root / name)}" for name in source_files(root)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _run(command: Sequence[str], root: Path) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed arguments, uv found on PATH
            list(command), cwd=root, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise PackageError(f"{Path(command[0]).name} {command[1]} failed: {detail[0]}") from error
    return done.stdout


def uv_installer(root: Path, target: Path) -> None:
    """Install the locked runtime dependencies into ``target``: arm64 Lambda wheels only."""
    uv = shutil.which("uv")
    if uv is None:
        raise PackageError("uv is not on PATH; install it (see README.md)")
    exported = _run(
        [
            uv,
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
            "--format",
            "requirements.txt",
        ],
        root,
    )
    requirements = target.parent / "requirements.txt"
    requirements.write_text(exported, encoding="utf-8")
    _run(
        [
            uv,
            "pip",
            "install",
            "--target",
            str(target),
            "--python-version",
            PYTHON_VERSION,
            "--python-platform",
            PLATFORM,
            "--only-binary",
            ":all:",
            "--no-deps",
            "--require-hashes",
            "--link-mode",
            "copy",
            "-r",
            str(requirements),
        ],
        root,
    )


def commit_epoch(root: Path) -> int:
    """The archive's timestamp: SOURCE_DATE_EPOCH, or the time of the commit checked out."""
    configured = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if configured:
        return int(configured)
    git = shutil.which("git")
    if git is None:
        raise PackageError("git is not on PATH; set SOURCE_DATE_EPOCH instead")
    return int(_run([git, "log", "-1", "--format=%ct"], root).strip())


def _left_out(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if parts[0] in ("bin", ".lock") or "__pycache__" in parts or relative.suffix == ".pyc":
        return True
    return len(parts) == 2 and parts[0].endswith(".dist-info") and parts[1] in LEFT_OUT_RECORDS


def collect(root: Path, dependencies: Path) -> dict[str, Path]:
    """Every file of the package, by its path in the archive."""
    entries: dict[str, Path] = {}
    for path in sorted(dependencies.rglob("*")):
        relative = PurePosixPath(path.relative_to(dependencies).as_posix())
        if path.is_file() and not _left_out(relative):
            entries[relative.as_posix()] = path
    if any(name.split("/", 1)[0] == "agents" for name in entries):
        raise PackageError("a dependency installs a package named agents, which the code needs")
    for name in source_files(root):
        if name.startswith("agents/"):
            entries[name] = root / name
    return entries


def write_zip(entries: dict[str, Path], zip_path: Path, epoch: int) -> None:
    """Write the archive with sorted entries, fixed permissions and one timestamp."""
    stamp = time.gmtime(max(epoch, ZIP_EPOCH))[:6]
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.create_system = 3
            mode = 0o755 if ".so" in PurePosixPath(name).suffixes else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name].read_bytes(), compresslevel=9)


def build_package(
    root: Path, output_dir: Path, install: Installer = uv_installer, epoch: int | None = None
) -> Package:
    """Build ``functions-<source hash>.zip`` and its manifest in ``output_dir``."""
    digest = source_hash(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / f".staging-{digest[:12]}"
    shutil.rmtree(staging, ignore_errors=True)
    dependencies = staging / "python"
    dependencies.mkdir(parents=True)
    try:
        install(root, dependencies)
        entries = collect(root, dependencies)
        zip_path = output_dir / f"functions-{digest}.zip"
        write_zip(entries, zip_path, epoch if epoch is not None else commit_epoch(root))
        manifest = "".join(f"{file_sha256(entries[name])}  {name}\n" for name in sorted(entries))
        manifest_path = output_dir / f"functions-{digest}.manifest.txt"
        manifest_path.write_text(manifest, encoding="utf-8")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    for old in output_dir.glob("functions-*"):
        if old not in (zip_path, manifest_path):
            old.unlink()
    return Package(zip_path, manifest_path, digest, manifest, len(entries))


def main(argv: Sequence[str] | None = None, *, install: Installer = uv_installer) -> int:
    """Build the package and print its manifest; return the exit status."""
    parser = argparse.ArgumentParser(
        description="Build the Lambda functions' package reproducibly."
    )
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "build" / "lambda")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        package = build_package(args.repo_root, args.output_dir, install)
    except (PackageError, OSError, ValueError) as error:
        print(f"package: {error}", file=sys.stderr)
        return 1
    manifest_sha256 = hashlib.sha256(package.manifest.encode("utf-8")).hexdigest()
    print(package.manifest, end="")
    print(
        f"package: {package.zip_path.name}: {package.file_count} files\n"
        f"package: source hash   {package.source_hash}\n"
        f"package: manifest sha256 {manifest_sha256}  (compare this line with CI's)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
