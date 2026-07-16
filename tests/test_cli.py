from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import typer

from cv_radar.cli import _today_configured


def test_today_uses_configured_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RADAR_TIMEZONE", "Pacific/Kiritimati")

    assert _today_configured() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()


def test_today_rejects_invalid_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RADAR_TIMEZONE", "not/a-timezone")

    with pytest.raises(typer.BadParameter, match="RADAR_TIMEZONE"):
        _today_configured()
