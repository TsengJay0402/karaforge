from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from karaforge.errors import ModelError
from karaforge.models.registry import ModelSpec, get_model, load_registry

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_registry_is_not_empty() -> None:
    assert len(load_registry()) > 0


def test_registry_ids_match_keys() -> None:
    registry = load_registry()
    for key, spec in registry.items():
        assert spec.id == key


def test_file_entries_are_well_formed() -> None:
    for spec in load_registry().values():
        for file in spec.files:
            assert _SHA256.match(file.sha256)
            assert file.size >= 0
            assert file.url.startswith("https://")
            assert ".." not in file.path
            assert not file.path.startswith("/")


def test_paths_are_unique_within_a_model() -> None:
    for spec in load_registry().values():
        paths = [file.path for file in spec.files]
        assert len(paths) == len(set(paths))


def test_requires_reference_existing_models() -> None:
    registry = load_registry()
    for spec in registry.values():
        for dependency in spec.requires:
            assert dependency in registry


def test_registry_contains_expected_models() -> None:
    registry = load_registry()
    for model_id in (
        "whisper-small",
        "whisper-base",
        "uvr-mdxnet-kara-2",
        "uvr-metadata",
    ):
        assert model_id in registry


def test_uvr_separator_shares_folder_and_requires_metadata() -> None:
    registry = load_registry()
    separator = registry["uvr-mdxnet-kara-2"]
    assert separator.folder == "uvr"
    assert "uvr-metadata" in separator.requires
    metadata = registry["uvr-metadata"]
    assert metadata.folder == "uvr"


def test_whisper_small_folder_is_its_id() -> None:
    assert load_registry()["whisper-small"].folder == "whisper-small"


def test_total_size_is_sum_of_file_sizes() -> None:
    for spec in load_registry().values():
        assert spec.total_size == sum(file.size for file in spec.files)


def test_get_model_unknown_id_raises() -> None:
    with pytest.raises(ModelError):
        get_model("不存在的模型")


def test_model_spec_is_frozen() -> None:
    spec = load_registry()["whisper-small"]
    with pytest.raises(ValidationError):
        spec.title = "another title"


def test_model_file_is_frozen() -> None:
    spec = load_registry()["whisper-small"]
    file = spec.files[0]
    with pytest.raises(ValidationError):
        file.path = "other.bin"


def test_model_spec_fields() -> None:
    spec: ModelSpec = load_registry()["whisper-small"]
    assert spec.kind == "asr"
    assert spec.files
