"""Schema migrations for ``project.json``.

A migration is a pure function that takes the raw JSON object of version ``N`` and returns
the object of version ``N + 1``.  :func:`migrate` chains them until the document reaches
:data:`~karaforge.project.schema.SCHEMA_VERSION`.  Migrations work on plain dictionaries (not
on the Pydantic models) so that they keep working after the models change again.

To add one::

    @migration(from_version=1)
    def _add_some_field(data: JsonObject) -> JsonObject:
        data.setdefault("some_field", "default")
        return data

and bump ``SCHEMA_VERSION`` to 2.  Add a fixture of the old format under
``tests/fixtures/projects/`` and a test in ``tests/unit/test_project_migrations.py``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from karaforge.errors import ProjectError
from karaforge.project.schema import SCHEMA_VERSION

JsonObject = dict[str, Any]
Migration = Callable[[JsonObject], JsonObject]

_MIGRATIONS: dict[int, Migration] = {}


def migration(from_version: int) -> Callable[[Migration], Migration]:
    """Register a function that upgrades a document from ``from_version`` to the next one."""

    def decorator(function: Migration) -> Migration:
        if from_version in _MIGRATIONS:
            raise RuntimeError(f"duplicate migration from schema version {from_version}")
        _MIGRATIONS[from_version] = function
        return function

    return decorator


def migrate(
    data: JsonObject,
    *,
    target_version: int = SCHEMA_VERSION,
    migrations: dict[int, Migration] | None = None,
) -> tuple[JsonObject, list[int]]:
    """Upgrade a raw project document to ``target_version``.

    Args:
        data: The parsed ``project.json``.  It is not modified.
        target_version: Version to upgrade to (the current schema version by default).
        migrations: Registry to use; defaults to the built-in one.  Exposed for tests.

    Returns:
        The upgraded document and the list of versions that were migrated *from*
        (empty when the document was already current).

    Raises:
        ProjectError: If the version is missing, newer than this build supports, or there is
            no migration path.
    """
    registry = _MIGRATIONS if migrations is None else migrations
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ProjectError(
            "專案檔缺少有效的 schema_version,無法判斷格式版本。",
            "The project file has no valid schema_version.",
            detail=f"schema_version={version!r}",
        )
    if version > target_version:
        raise ProjectError(
            f"這個專案是用較新版本的 KaraForge 建立的(格式版本 {version}),"
            f"目前的程式只支援到版本 {target_version}。",
            f"This project was created by a newer KaraForge (schema version {version}); "
            f"this build supports up to version {target_version}.",
            hint_zh="請更新 KaraForge 後再開啟這個專案。",
            hint_en="Update KaraForge to open this project.",
        )
    current = copy.deepcopy(data)
    applied: list[int] = []
    while version < target_version:
        step = registry.get(version)
        if step is None:
            raise ProjectError(
                f"無法把專案從格式版本 {version} 升級到 {target_version}:缺少遷移步驟。",
                f"Cannot upgrade the project from schema version {version} to {target_version}: "
                "no migration is registered.",
            )
        current = step(current)
        applied.append(version)
        version += 1
        current["schema_version"] = version
    return current, applied
