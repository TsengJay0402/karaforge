from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from karaforge.errors import ProjectError
from karaforge.project import SCHEMA_VERSION, Project, ProjectStore
from karaforge.project import migrations as migrations_module
from karaforge.project.migrations import JsonObject, migrate, migration

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "projects"


def test_already_current_version_is_unchanged() -> None:
    data: JsonObject = {"schema_version": SCHEMA_VERSION, "revision": 3}
    result, applied = migrate(data)
    assert result == {"schema_version": SCHEMA_VERSION, "revision": 3}
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


def test_newer_version_than_this_build_asks_to_update() -> None:
    with pytest.raises(ProjectError, match=f"supports up to version {SCHEMA_VERSION}") as info:
        migrate({"schema_version": SCHEMA_VERSION + 1})
    assert "更新" in (info.value.hint_zh or "")


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


def test_every_version_up_to_the_current_one_has_a_migration() -> None:
    registry = migrations_module._MIGRATIONS  # pyright: ignore[reportPrivateUsage]
    assert sorted(registry) == list(range(1, SCHEMA_VERSION))


# ------------------------------------------------------------------ real migrations


def spec_example() -> JsonObject:
    """The version-1 document printed in the specification (§4.2)."""
    return json.loads((FIXTURES / "v1-spec-example.json").read_text(encoding="utf-8"))


def test_version_1_project_is_upgraded_to_the_current_version() -> None:
    original = spec_example()
    migrated, applied = migrate(original)
    assert applied == list(range(1, SCHEMA_VERSION))
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["lines"][0]["time_hint"] is None
    assert migrated["meta"]["lyrics_source"] == "user"
    # Nothing else changed.
    without_additions = json.loads(json.dumps(migrated))
    del without_additions["lines"][0]["time_hint"]
    del without_additions["meta"]["lyrics_source"]
    without_additions["schema_version"] = 1
    assert without_additions == original

    project = Project.model_validate(migrated)
    assert project.meta.lyrics_source == "user"
    token = project.lines[0].tokens[0]
    assert (token.text, token.start_ms, token.end_ms, token.ruby) == ("我", 15230, 15610, "ㄨㄛˇ")
    assert project.revision == 42 and project.analysis.vocal_regions == [(1200, 15800)]
    assert project.lines[0].time_hint is None


def test_version_2_project_gains_the_lyrics_source() -> None:
    version_2 = spec_example()
    version_2["schema_version"] = 2
    version_2["lines"][0]["time_hint"] = [15000, 18000]
    migrated, applied = migrate(version_2)
    assert applied == [2]
    assert migrated["meta"]["lyrics_source"] == "user"
    assert migrated["lines"][0]["time_hint"] == [15000, 18000]
    # A document that already says where its lyrics came from keeps that.
    version_2["meta"]["lyrics_source"] = "asr"
    assert migrate(version_2)[0]["meta"]["lyrics_source"] == "asr"
    assert Project.model_validate(migrated).schema_version == SCHEMA_VERSION


def test_store_opens_an_old_project_and_saves_it_in_the_new_format(tmp_path: Path) -> None:
    root = tmp_path / "old.kfproj"
    root.mkdir()
    shutil.copyfile(FIXTURES / "v1-spec-example.json", root / "project.json")
    store = ProjectStore(root)
    project = store.load()
    assert project.schema_version == SCHEMA_VERSION
    # Loading does not touch the file; the upgrade is written with the next save.
    assert json.loads((root / "project.json").read_text(encoding="utf-8"))["schema_version"] == 1
    store.save(project, expected_revision=42)
    saved = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == SCHEMA_VERSION
    assert saved["revision"] == 43
    assert saved["lines"][0]["time_hint"] is None
    backup = json.loads((root / "project.json.bak").read_text(encoding="utf-8"))
    assert backup["schema_version"] == 1


def test_project_from_a_future_version_is_refused_with_a_clear_message(tmp_path: Path) -> None:
    root = tmp_path / "future.kfproj"
    root.mkdir()
    document = spec_example()
    document["schema_version"] = SCHEMA_VERSION + 5
    (root / "project.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProjectError) as info:
        ProjectStore(root).load()
    assert str(SCHEMA_VERSION + 5) in info.value.message_zh
    assert "Update KaraForge" in (info.value.hint_en or "")
