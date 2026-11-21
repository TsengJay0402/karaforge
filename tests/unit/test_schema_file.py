from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from karaforge.project.schema import SCHEMA_VERSION


def _load_exporter(repo_root: Path) -> object:
    spec = importlib.util.spec_from_file_location(
        "export_schema", repo_root / "scripts" / "export_schema.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_json_schema_is_up_to_date(repo_root: Path) -> None:
    exporter = _load_exporter(repo_root)
    committed = (repo_root / "docs" / "project.schema.json").read_text(encoding="utf-8")
    expected: str = exporter.schema_text()  # type: ignore[attr-defined]
    assert committed == expected, "run `python scripts/export_schema.py`"


def test_schema_describes_the_documented_structure(repo_root: Path) -> None:
    schema = json.loads((repo_root / "docs" / "project.schema.json").read_text(encoding="utf-8"))
    assert str(SCHEMA_VERSION) in schema["title"]
    assert set(schema["properties"]) == {
        "schema_version",
        "revision",
        "meta",
        "media",
        "analysis",
        "singers",
        "lines",
        "style",
        "render",
    }
    token = schema["$defs"]["Token"]["properties"]
    assert set(token) == {
        "text",
        "start_ms",
        "end_ms",
        "ruby",
        "ruby_source",
        "confidence",
        "locked",
        "source",
    }
    assert schema["$defs"]["Token"]["additionalProperties"] is False
