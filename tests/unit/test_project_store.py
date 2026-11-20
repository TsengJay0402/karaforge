from __future__ import annotations

import json
from pathlib import Path

import pytest

from karaforge.errors import ProjectError, RevisionConflictError
from karaforge.project.schema import Line, Project, Token
from karaforge.project.store import ProjectStore, slugify


@pytest.fixture
def project() -> Project:
    return Project(
        lines=[Line(id="L001", tokens=[Token(text="你", start_ms=100, end_ms=200)])],
    )


def test_create_builds_folder_structure_and_revision_zero(tmp_path: Path, project: Project) -> None:
    root = tmp_path / "song.kfproj"
    store = ProjectStore(root)
    store.create(project)
    assert (root / "media").is_dir()
    assert (root / "cache").is_dir()
    assert (root / "exports").is_dir()
    assert (root / "project.json").is_file()
    assert project.revision == 0
    assert json.loads((root / "project.json").read_text(encoding="utf-8"))["revision"] == 0


def test_create_twice_raises_but_overwrite_replaces(tmp_path: Path, project: Project) -> None:
    store = ProjectStore(tmp_path / "song.kfproj")
    store.create(project)
    with pytest.raises(ProjectError):
        store.create(Project())
    (store.paths.media / "leftover.txt").write_text("stale", encoding="utf-8")
    replacement = Project()
    store.create(replacement, overwrite=True)
    assert replacement.revision == 0
    assert not (store.paths.media / "leftover.txt").exists()
    assert store.load() == replacement


def test_load_returns_the_stored_document(tmp_path: Path, project: Project) -> None:
    store = ProjectStore(tmp_path / "song.kfproj")
    store.create(project)
    loaded = store.load()
    assert loaded == project
    assert loaded.lines[0].tokens[0].start_ms == 100


def test_save_bumps_revision_on_disk_and_in_place(tmp_path: Path, project: Project) -> None:
    store = ProjectStore(tmp_path / "song.kfproj")
    store.create(project)
    for expected in (1, 2, 3):
        saved = store.save(project)
        assert saved is project
        assert project.revision == expected
        assert store.current_revision() == expected


def test_revision_conflict_writes_nothing(tmp_path: Path, project: Project) -> None:
    store = ProjectStore(tmp_path / "song.kfproj")
    store.create(project)
    disk_before = (store.paths.project_file).read_bytes()
    with pytest.raises(RevisionConflictError):
        store.save(project, expected_revision=99)
    assert project.revision == 0
    assert store.paths.project_file.read_bytes() == disk_before


def test_save_leaves_a_backup_of_the_previous_revision(tmp_path: Path, project: Project) -> None:
    store = ProjectStore(tmp_path / "song.kfproj")
    store.create(project)
    assert not (tmp_path / "song.kfproj" / "project.json.bak").exists()
    store.save(project)
    backup = json.loads((store.paths.project_file.with_name("project.json.bak")).read_text())
    assert backup["revision"] == 0
    store.save(project)
    backup = json.loads((store.paths.project_file.with_name("project.json.bak")).read_text())
    assert backup["revision"] == 1


def test_load_rejects_invalid_json(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "broken.kfproj")
    store.paths.root.mkdir()
    store.paths.project_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProjectError):
        store.load()


def test_load_rejects_non_object_json(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "broken.kfproj")
    store.paths.root.mkdir()
    store.paths.project_file.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProjectError):
        store.load()


def test_load_missing_folder_raises(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "missing.kfproj")
    with pytest.raises(ProjectError):
        store.load()


def test_load_rejects_document_that_fails_validation(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "invalid.kfproj")
    store.paths.root.mkdir()
    store.paths.project_file.write_text(
        json.dumps({"schema_version": 1, "lines": [{"id": "L001", "singer": "ghost"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ProjectError):
        store.load()


def test_paths_resolve_and_relative(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "song.kfproj")
    assert store.paths.resolve(None) is None
    assert store.paths.resolve("media/song.wav") == tmp_path / "song.kfproj" / "media" / "song.wav"
    media_file = store.paths.media / "song.wav"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"")
    assert store.paths.relative(media_file) == "media/song.wav"


def test_slugify_keeps_cjk_and_strips_unsafe_characters() -> None:
    assert slugify("好聽的歌") == "好聽的歌"
    assert slugify('a/b:c*d?e"f<g>h|i') == "a-b-c-d-e-f-g-h-i"
    assert slugify("") == "project"
    assert slugify("///") == "project"
    assert slugify("  spaced  out  ") == "spaced-out"
