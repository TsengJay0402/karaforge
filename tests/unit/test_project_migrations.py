from __future__ import annotations

import pytest

from karaforge.errors import ProjectError
from karaforge.project import migrations as migrations_module
from karaforge.project.migrations import JsonObject, migrate, migration


def test_already_current_version_is_unchanged() -> None:
    data: JsonObject = {"schema_version": 1, "revision": 3}
    result, applied = migrate(data)
    assert result == {"schema_version": 1, "revision": 3}
    assert applied == []


def test_input_dict_is_not_mutated() -> None:
    data: JsonObject = {"schema_version": 1}

    def add_field(document: JsonObject) -> JsonObject:
        document["added"] = True  # mutating the working copy must not leak into ``data``
        return document

    result, applied = migrate(data, target_version=2, migrations={1: add_field})
    assert result == {"schema_version": 2, "added": True}
    assert applied == [1]
    assert data == {"schema_version": 1}


@pytest.mark.parametrize("bad_version", [None, "1", 1.0, True, False, -1])
def test_invalid_schema_version_raises(bad_version: object) -> None:
    with pytest.raises(ProjectError):
        migrate({"schema_version": bad_version})


def test_missing_schema_version_raises() -> None:
    with pytest.raises(ProjectError):
        migrate({"revision": 0})


def test_newer_version_than_target_raises_with_update_hint() -> None:
    with pytest.raises(ProjectError, match="supports up to version 1"):
        migrate({"schema_version": 2})


def test_newer_version_than_explicit_target_raises() -> None:
    with pytest.raises(ProjectError):
        migrate({"schema_version": 3}, target_version=2)


def test_missing_migration_step_raises() -> None:
    with pytest.raises(ProjectError, match="no migration is registered"):
        migrate({"schema_version": 1}, target_version=3, migrations={})


def test_custom_registry_chains_two_migrations() -> None:
    def step_1(document: JsonObject) -> JsonObject:
        upgraded = dict(document)
        upgraded["added"] = "new field"
        return upgraded

    def step_2(document: JsonObject) -> JsonObject:
        renamed = {key: value for key, value in document.items() if key != "added"}
        renamed["renamed"] = document["added"]
        return renamed

    result, applied = migrate(
        {"schema_version": 1, "revision": 7},
        target_version=3,
        migrations={1: step_1, 2: step_2},
    )
    assert result == {"schema_version": 3, "revision": 7, "renamed": "new field"}
    assert applied == [1, 2]


def test_duplicate_migration_registration_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrations_module, "_MIGRATIONS", {})
    registry = migrations_module._MIGRATIONS  # pyright: ignore[reportPrivateUsage]

    @migration(from_version=1)
    def first(document: JsonObject) -> JsonObject:
        return document

    with pytest.raises(RuntimeError, match="duplicate migration from schema version 1"):

        @migration(from_version=1)
        def second(document: JsonObject) -> JsonObject:
            return document

    assert registry == {1: first}
