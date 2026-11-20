"""Write the JSON Schema of ``project.json`` to ``docs/project.schema.json``.

Run after changing ``karaforge.project.schema``::

    uv run python scripts/export_schema.py

A unit test fails when the committed file is out of date.
"""

from __future__ import annotations

import json
from pathlib import Path

from karaforge.project.schema import SCHEMA_VERSION, Project

TARGET = Path(__file__).resolve().parent.parent / "docs" / "project.schema.json"


def schema_text() -> str:
    """The schema as pretty-printed JSON text."""
    schema = Project.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://karaforge.dev/schema/project-v{SCHEMA_VERSION}.json"
    schema["title"] = f"KaraForge project.json (schema version {SCHEMA_VERSION})"
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    """Write the schema file."""
    TARGET.write_text(schema_text(), encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
