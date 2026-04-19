import pytest

from running_coach.config.settings import Settings


def _settings(**overrides):
    return Settings(
        garmin_email="user@example.com",
        garmin_password="secret",
        gemini_api_key="key",
        **overrides,
    )


def test_parsed_schedule_times_accepts_multiple_user_times():
    settings = _settings(schedule_times="5,17:30")

    assert settings.parsed_schedule_times() == ["05:00", "17:30"]


def test_parsed_schedule_times_falls_back_to_legacy_hour():
    settings = _settings(schedule_times="", schedule_hour=6)

    assert settings.parsed_schedule_times() == ["06:00"]


def test_parsed_schedule_times_rejects_invalid_time():
    settings = _settings(schedule_times="25:00")

    with pytest.raises(ValueError, match="Invalid schedule time"):
        settings.parsed_schedule_times()
