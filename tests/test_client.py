"""
Tests for humblebundle_scraper.client login success/failure handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import requests

from src.client import (
    HumbleAuthenticationError,
    HumbleClient,
    HumbleRequestError,
    TwoFactorRequiredError,
)


def _response(json_data=None, status_code=200, raise_value_error=False):
    """Build a stub ``requests.Response``-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    if raise_value_error:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = json_data
    return resp


def test_login_result_success_returns() -> None:
    # Explicit success must not raise.
    HumbleClient._raise_for_login_result(_response({"success": True}))


def test_login_result_humble_guard_raises_two_factor() -> None:
    with pytest.raises(TwoFactorRequiredError):
        HumbleClient._raise_for_login_result(
            _response({"humble_guard_required": True})
        )


def test_login_result_twofactor_flag_raises_two_factor() -> None:
    with pytest.raises(TwoFactorRequiredError):
        HumbleClient._raise_for_login_result(
            _response({"twofactor_required": True})
        )


def test_login_result_field_errors_are_flattened() -> None:
    with pytest.raises(HumbleAuthenticationError, match="bad password"):
        HumbleClient._raise_for_login_result(
            _response({"errors": {"password": ["bad password"]}})
        )


def test_login_result_json_without_success_is_failure() -> None:
    with pytest.raises(HumbleAuthenticationError):
        HumbleClient._raise_for_login_result(_response({"foo": "bar"}))


def test_login_result_no_json_401_is_invalid_credentials() -> None:
    with pytest.raises(HumbleAuthenticationError, match="Invalid email"):
        HumbleClient._raise_for_login_result(
            _response(status_code=401, raise_value_error=True)
        )


def test_login_result_no_json_ok_is_still_failure() -> None:
    # A 200 with no parseable confirmation must not be treated as success.
    with pytest.raises(HumbleAuthenticationError):
        HumbleClient._raise_for_login_result(
            _response(status_code=200, raise_value_error=True)
        )


def test_list_orders_timeout_raises_request_error() -> None:
    client = HumbleClient()
    client.session.get = MagicMock(side_effect=requests.Timeout())  # type: ignore[assignment]
    with pytest.raises(HumbleRequestError, match="library"):
        client.list_orders()


def test_get_order_details_timeout_raises_request_error() -> None:
    client = HumbleClient()
    client.session.get = MagicMock(side_effect=requests.Timeout())  # type: ignore[assignment]
    with pytest.raises(HumbleRequestError, match="order abc"):
        client.get_order_details("abc")


def test_fetch_csrf_token_uses_existing_cookie() -> None:
    client = HumbleClient()
    client.session.cookies.set("csrf_cookie", "tok123", domain=".humblebundle.com")
    assert client._fetch_csrf_token() == "tok123"


def test_fetch_csrf_token_missing_after_fetch_raises() -> None:
    client = HumbleClient()
    client.session.get = MagicMock(  # type: ignore[assignment]
        return_value=_response(status_code=200)
    )
    with pytest.raises(HumbleAuthenticationError, match="CSRF token"):
        client._fetch_csrf_token()
