"""The environment must not contain licences the documentation does not account for.

KaraForge is Apache-2.0.  Its dependencies are listed in ``docs/LICENSES.md``, but a list kept
by hand only covers what somebody thought of: ``diffq`` (CC-BY-NC) came in through
``audio-separator`` and went unnoticed until a Docker build failed on it.  These tests look
at every installed package instead, through ``scripts/scan_licenses.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def scanner(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scan_licenses", repo_root / "scripts" / "scan_licenses.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up while the class body is evaluated.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_no_undocumented_copyleft_or_non_commercial_package_is_installed(
    scanner: ModuleType,
) -> None:
    findings = scanner.scan()
    assert findings.total > 50, "the scan did not see the environment"
    unexpected = [
        f"{package.name} ({package.licence or 'no licence stated'})"
        for package in findings.unexpected
    ]
    assert not unexpected, (
        f"packages with a licence docs/LICENSES.md does not account for: {unexpected}. "
        "If it is diffq or soynlp, the environment was not installed with `uv sync`; "
        "otherwise decide whether the dependency is acceptable and document it."
    )


def test_the_scan_recognises_restrictive_licences(scanner: ModuleType) -> None:
    package = scanner.Package
    packages = [
        package("permissive", "1.0", "MIT"),
        package("apache", "2.0", "Apache-2.0; Apache Software License"),
        package("copyleft", "1.0", "GNU General Public License v3 (GPLv3)"),
        package("weak-copyleft", "1.0", "LGPL-2.1-or-later"),
        package(
            "non_commercial", "1.0", "Creative Commons Attribution-NonCommercial 4.0 International"
        ),
        package("silent", "1.0", ""),
        package("diffq", "0.2.4", "Creative Commons Attribution-NonCommercial 4.0 International"),
        package("soxr", "1.1.0", "LGPL-2.1-or-later"),
    ]
    findings = scanner.scan(packages)
    assert [item.name for item in findings.restrictive] == [
        "copyleft",
        "weak-copyleft",
        "non_commercial",
        "soxr",
    ]
    assert [item.name for item in findings.unstated] == ["silent"]
    assert [item.name for item in findings.excluded_but_installed] == ["diffq"]
    # soxr is documented; everything else here is not.
    assert [item.name for item in findings.unexpected] == [
        "copyleft",
        "weak-copyleft",
        "non_commercial",
        "silent",
        "diffq",
    ]


def test_excluded_packages_are_excluded_in_the_project_file(
    scanner: ModuleType, repo_root: Path
) -> None:
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    for name in scanner.EXCLUDED:
        assert f"\"{name} ; sys_platform == 'never'\"" in pyproject, name
