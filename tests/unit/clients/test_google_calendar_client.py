"""Google Calendar client tests."""

from __future__ import annotations

from running_coach.clients.google_calendar.client import GoogleCalendarClient


def test_disabled_google_calendar_client_skips_authentication():
    client = GoogleCalendarClient(enabled=False)

    service = client.authenticate()

    assert service is None
    assert client.sync_service is None
    assert client.is_authenticated is False


def test_google_calendar_client_keeps_db_token_info():
    token_info = {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }

    client = GoogleCalendarClient(token_info=token_info)

    assert client.token_info is token_info
    assert client.enabled is True
