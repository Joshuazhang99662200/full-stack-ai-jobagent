import io
import sys

import pytest

from jobagent.cli.app import main


class LegacyStream(io.StringIO):
    """Stand-in for a console bound to a non-UTF-8 codec such as cp936."""

    def __init__(self, encoding: str) -> None:
        super().__init__()
        self._encoding = encoding
        self.reconfigured: dict[str, str] = {}

    @property
    def encoding(self) -> str:
        return self._encoding

    def reconfigure(self, *, encoding: str, errors: str) -> None:  # type: ignore[override]
        self.reconfigured = {"encoding": encoding, "errors": errors}
        self._encoding = encoding


@pytest.mark.parametrize("encoding", ["cp936", "gbk", "ascii"])
def test_legacy_console_is_reconfigured_to_utf8(
    monkeypatch: pytest.MonkeyPatch, encoding: str
) -> None:
    stdout = LegacyStream(encoding)
    stderr = LegacyStream(encoding)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    main()

    assert stdout.reconfigured == {"encoding": "utf-8", "errors": "backslashreplace"}
    assert stderr.reconfigured == {"encoding": "utf-8", "errors": "backslashreplace"}


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8", "utf8"])
def test_utf8_console_is_left_alone(monkeypatch: pytest.MonkeyPatch, encoding: str) -> None:
    stdout = LegacyStream(encoding)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", LegacyStream(encoding))

    main()

    assert stdout.reconfigured == {}


def test_stream_without_reconfigure_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    main()
