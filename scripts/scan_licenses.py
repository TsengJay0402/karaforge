"""List the installed Python packages whose licence is not a permissive one.

KaraForge is Apache-2.0 and must not install or ship GPL or non-commercial code by default.
``docs/LICENSES.md`` lists the direct dependencies by hand; this script looks at *everything*
in the current environment, transitive dependencies included, and reports

* packages whose licence metadata mentions a copyleft or non-commercial licence,
* packages that state no licence at all,
* packages that are excluded on purpose (``diffq``, ``soynlp``) but are installed anyway.

Run it inside the environment to inspect::

    python scripts/scan_licenses.py

It exits with status 1 when it finds something ``docs/LICENSES.md`` does not account for.
A unit test runs the same check, so a new dependency that drags in such a package fails the
test suite.  The scan reads package metadata only: a package with wrong or missing metadata
slips through, and none of this is legal advice.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib.metadata import PackageMetadata, distributions

# Licence families that need a decision before they may be part of an install.
_RESTRICTIVE = re.compile(
    r"GPL|GNU (Lesser |Library |Affero )?General Public|Non-?Commercial|CC[- ]BY|"
    r"Creative Commons|Proprietary|SSPL|Commons Clause|research (use )?only",
    re.IGNORECASE,
)

# Packages the documentation accounts for: name -> (licence, where it comes from).
# Adding a line here is a licensing decision; record it in docs/LICENSES.md as well.
EXPECTED: dict[str, tuple[str, str]] = {
    "soxr": (
        "LGPL-2.1-or-later",
        "core: librosa resamples with it; unmodified, loaded as a library",
    ),
    "phonemizer-fork": ("GPL-3.0-or-later", "bench tools: a dependency of misaki"),
    "num2words": ("LGPL", "bench tools: a dependency of misaki"),
}

# Packages without licence metadata whose licence was looked up by hand.
EXPECTED_UNSTATED: dict[str, tuple[str, str]] = {
    "espeakng-loader": ("ships espeak-ng, GPL-3.0", "bench tools: a dependency of misaki"),
    "pyworld": ("MIT, per the licence file inside the package", "bench tools: the vocoder"),
}

# Excluded in pyproject.toml ([tool.uv] override-dependencies); must not be installed.
EXCLUDED: dict[str, str] = {
    "diffq": "CC-BY-NC-4.0; only audio-separator's Demucs code imports it, KaraForge never does",
    "diffq-fixed": "the Windows build of diffq",
    "soynlp": "GPL-3.0; only qwen-asr's own Korean text preparation imports it, which "
    "KaraForge never calls",
}


@dataclass(frozen=True)
class Package:
    """An installed distribution and what its metadata says about its licence."""

    name: str
    version: str
    licence: str

    @property
    def key(self) -> str:
        """The normalised name used for look-ups."""
        return re.sub(r"[-_.]+", "-", self.name).lower()


@dataclass(frozen=True)
class Findings:
    """The outcome of a scan."""

    total: int
    restrictive: list[Package]
    unstated: list[Package]
    excluded_but_installed: list[Package]

    @property
    def unexpected(self) -> list[Package]:
        """Everything the documentation does not account for."""
        return [
            *(package for package in self.restrictive if package.key not in EXPECTED),
            *(package for package in self.unstated if package.key not in EXPECTED_UNSTATED),
            *self.excluded_but_installed,
        ]


def _licence_of(metadata: PackageMetadata) -> str:
    """Everything the metadata says about the licence, on one line."""
    parts: list[str] = []
    expression = metadata.get("License-Expression")
    if expression:
        parts.append(expression.strip())
    text = metadata.get("License")
    if text and text.strip() and text.strip().upper() != "UNKNOWN":
        # Some packages paste the whole licence text here; the first line names it.
        parts.append(text.strip().splitlines()[0][:80])
    classifiers = [str(item) for item in metadata.get_all("Classifier") or []]
    parts.extend(
        classifier.split("::")[-1].strip()
        for classifier in classifiers
        if classifier.startswith("License ::")
    )
    return "; ".join(dict.fromkeys(parts))


def installed() -> list[Package]:
    """Every distribution in the current environment."""
    found: dict[str, Package] = {}
    for distribution in distributions():
        metadata = distribution.metadata
        name = metadata.get("Name")
        if not name:
            continue
        package = Package(name, distribution.version, _licence_of(metadata))
        found.setdefault(package.key, package)
    return sorted(found.values(), key=lambda package: package.key)


def scan(packages: list[Package] | None = None) -> Findings:
    """Sort the installed packages into the categories that need attention."""
    packages = installed() if packages is None else packages
    return Findings(
        total=len(packages),
        restrictive=[
            package
            for package in packages
            if package.key not in EXCLUDED and _RESTRICTIVE.search(package.licence)
        ],
        unstated=[
            package for package in packages if package.key not in EXCLUDED and not package.licence
        ],
        excluded_but_installed=[package for package in packages if package.key in EXCLUDED],
    )


def main() -> int:
    """Print the findings; return 1 when something is not accounted for."""
    findings = scan()
    print(f"{findings.total} packages installed.")
    print("\nCopyleft or non-commercial licence in the metadata:")
    for package in findings.restrictive:
        known = EXPECTED.get(package.key)
        note = f"documented — {known[1]}" if known else "NOT DOCUMENTED"
        print(f"  {package.name} {package.version}: {package.licence}  [{note}]")
    if not findings.restrictive:
        print("  none")
    print("\nNo licence stated in the metadata:")
    for package in findings.unstated:
        known = EXPECTED_UNSTATED.get(package.key)
        note = f"looked up: {known[0]} — {known[1]}" if known else "NOT DOCUMENTED"
        print(f"  {package.name} {package.version}  [{note}]")
    if not findings.unstated:
        print("  none")
    for package in findings.excluded_but_installed:
        print(
            f"\n{package.name} {package.version} is installed although KaraForge excludes it "
            f"({EXCLUDED[package.key]}).\n"
            "  Install with `uv sync` (see README), or remove it: pip uninstall "
            f"{package.name}"
        )
    if findings.unexpected:
        print("\nNot accounted for in docs/LICENSES.md:")
        for package in findings.unexpected:
            print(f"  {package.name} {package.version}: {package.licence or 'no licence stated'}")
        return 1
    print("\nNothing unexpected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
