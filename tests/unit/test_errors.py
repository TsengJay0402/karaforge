from __future__ import annotations

import pytest

from karaforge.errors import JobCancelledError, KaraForgeError, MediaError
from karaforge.runtime import CancelToken, subprogress


def test_user_message_languages() -> None:
    error = MediaError("讀不到檔案", "Cannot read file", hint_zh="換個檔案", hint_en="Try another")
    assert error.user_message("zh") == "讀不到檔案\n換個檔案"
    assert error.user_message("en") == "Cannot read file\nTry another"
    assert error.code == "media_error"


def test_to_dict_and_str_include_detail() -> None:
    error = KaraForgeError("壞了", "Broken", detail="exit 1")
    assert error.to_dict()["detail"] == "exit 1"
    assert str(error) == "Broken (exit 1)"
    assert str(KaraForgeError("壞了", "Broken")) == "Broken"


def test_cancel_token() -> None:
    token = CancelToken()
    assert not token.cancelled
    token.raise_if_cancelled()
    token.cancel()
    assert token.cancelled
    assert token.wait(0.0)
    with pytest.raises(JobCancelledError):
        token.raise_if_cancelled()


def test_subprogress_maps_and_clamps() -> None:
    seen: list[tuple[float, str]] = []
    child = subprogress(lambda fraction, message: seen.append((fraction, message)), 0.2, 0.6)
    child(0.0, "a")
    child(0.5, "b")
    child(2.0, "c")
    assert seen == [(0.2, "a"), (pytest.approx(0.4), "b"), (pytest.approx(0.6), "c")]
