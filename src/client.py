"""
HTTP client and login handling for Humble Bundle.

Notes
-----
Humble Bundle does not publish a stable public API for login, and the
endpoints or payloads used here may need to be adjusted to match the
current site behaviour. Use your browser's network inspector to confirm
the actual login request if this script fails to authenticate.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


LOGIN_PAGE_URL = "https://www.humblebundle.com/login"
LOGIN_URL = "https://www.humblebundle.com/processlogin"
LIBRARY_URL = "https://www.humblebundle.com/api/v1/user/order"
ORDER_URL_TEMPLATE = "https://www.humblebundle.com/api/v1/order/{order_id}?all_tiers=true&wallet=true"

# Cookie Humble Bundle uses to carry the authenticated session.
SESSION_COOKIE_NAME = "_simpleauth_sess"
COOKIE_DOMAIN = ".humblebundle.com"

# Humble Bundle protects the login POST with a CSRF token: the value of
# the ``csrf_cookie`` cookie must be echoed back in this request header.
CSRF_COOKIE_NAME = "csrf_cookie"
CSRF_HEADER_NAME = "CSRF-Prevention-Token"

# Network timeout (connect, read) applied to auth/probe requests so a
# stalled connection cannot hang the process forever.
REQUEST_TIMEOUT = (10, 30)


class HumbleRequestError(RuntimeError):
    """Raised when a request to Humble Bundle times out or otherwise fails."""


class HumbleAuthenticationError(RuntimeError):
    """Raised when authentication with Humble Bundle fails."""


class TwoFactorRequiredError(HumbleAuthenticationError):
    """Raised when the server indicates that a 2FA code is required."""


@dataclass
class HumbleOrder:
    """Represents a single Humble Bundle order."""

    gamekey: str
    product: str


class HumbleClient:
    """
    Simple wrapper around the Humble Bundle HTTP API.

    This client is intentionally minimal and focuses on:

    - Logging in using email, password, and optional 2FA code.
    - Enumerating library orders for the account.
    - Fetching full order details, including download structures.
    """

    def __init__(self, session_file: Optional[Path] = None) -> None:
        self.session = requests.Session()
        # Use a desktop-like user agent to avoid basic bot checks.
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
        )
        self.session_file = Path(session_file) if session_file else None
        if self.session_file is not None and self.session_file.exists():
            self.load_session()

    def set_session_cookie(self, value: str) -> None:
        """
        Authenticate using a session cookie value taken from a browser.

        This is the recommended path: it avoids storing the account
        password at rest. Copy the ``_simpleauth_sess`` cookie from a
        logged-in browser session and pass its value here.
        """
        self.session.cookies.set(
            SESSION_COOKIE_NAME, value.strip(), domain=COOKIE_DOMAIN
        )

    def load_session(self) -> None:
        """Restore previously saved cookies from ``self.session_file``."""
        if self.session_file is None:
            return
        try:
            data = json.loads(self.session_file.read_text())
        except (OSError, ValueError):
            return
        for name, value in data.items():
            self.session.cookies.set(name, value, domain=COOKIE_DOMAIN)

    def save_session(self) -> None:
        """
        Persist the current cookies to ``self.session_file`` with
        owner-only permissions (0600) so credentials are not left
        world-readable.
        """
        if self.session_file is None:
            return
        cookies = {
            c.name: c.value
            for c in self.session.cookies
            if c.domain.endswith("humblebundle.com")
        }
        if not cookies:
            return
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        # Create the file with 0600 from the start to avoid a brief
        # window where the cookie is world-readable.
        fd = os.open(
            self.session_file,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(fd, "w") as fh:
            json.dump(cookies, fh)
        os.chmod(self.session_file, stat.S_IRUSR | stat.S_IWUSR)

    def is_authenticated(self) -> bool:
        """
        Return ``True`` if the current session can access the library.

        Used to decide whether a password login is needed at all when a
        saved session or browser cookie is available.
        """
        try:
            response = self.session.get(
                LIBRARY_URL, timeout=REQUEST_TIMEOUT, allow_redirects=False
            )
        except requests.RequestException:
            return False
        if response.status_code != 200:
            return False
        try:
            response.json()
        except ValueError:
            return False
        return True

    def login(self, email: str, password: str, otp: Optional[str] = None) -> None:
        """
        Log into Humble Bundle.

        Parameters
        ----------
        email:
            Humble Bundle account email.
        password:
            Humble Bundle account password.
        otp:
            Optional two-factor authentication code.

        Raises
        ------
        TwoFactorRequiredError
            If the server indicates a 2FA token is required.
        HumbleAuthenticationError
            If login fails for any other reason.
        """
        csrf_token = self._fetch_csrf_token()

        payload: Dict[str, Any] = {
            "username": email,
            "password": password,
            "rememberme": "on",
        }
        if otp:
            # Humble Guard (emailed code) and authenticator codes are both
            # submitted under "guard"; "code" is kept for older flows.
            payload["guard"] = otp
            payload["code"] = otp

        response = self.session.post(
            LOGIN_URL,
            data=payload,
            headers={CSRF_HEADER_NAME: csrf_token},
            timeout=REQUEST_TIMEOUT,
        )

        self._raise_for_login_result(response)

        # Confirm the session really works rather than trusting the POST
        # alone, then persist it so later runs need no password.
        if not self.is_authenticated():
            raise HumbleAuthenticationError(
                "Login appeared to succeed but the session is not valid."
            )
        self.save_session()

    def _fetch_csrf_token(self) -> str:
        """
        Return the CSRF token Humble Bundle requires for ``processlogin``.

        The token is delivered as the ``csrf_cookie`` cookie when the
        login page is fetched.
        """
        token = self.session.cookies.get(CSRF_COOKIE_NAME)
        if token:
            return token
        try:
            response = self.session.get(
                LOGIN_PAGE_URL, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HumbleAuthenticationError(
                f"Could not reach Humble Bundle login page: {exc}"
            ) from exc
        token = self.session.cookies.get(CSRF_COOKIE_NAME)
        if not token:
            raise HumbleAuthenticationError(
                "Humble Bundle did not provide a CSRF token; the login "
                "flow may have changed."
            )
        return token

    @staticmethod
    def _raise_for_login_result(response: requests.Response) -> None:
        """
        Inspect the ``processlogin`` response and raise on failure.

        Humble Bundle answers with JSON. Success is an explicit
        ``{"success": true}``; failures carry ``errors`` and may flag a
        required second factor. Status code alone is not authoritative.
        """
        try:
            data = response.json()
        except ValueError:
            data = None

        if isinstance(data, dict):
            if data.get("success") is True:
                return

            if (
                data.get("humble_guard_required")
                or data.get("twofactor_required")
                or data.get("two_factor_required")
            ):
                raise TwoFactorRequiredError(
                    "Two-factor authentication code required."
                )

            errors = data.get("errors")
            if errors:
                if isinstance(errors, dict):
                    flat = [
                        str(m)
                        for msgs in errors.values()
                        for m in (msgs if isinstance(msgs, list) else [msgs])
                    ]
                    message = "; ".join(flat) or "Invalid credentials."
                else:
                    message = str(errors)
                raise HumbleAuthenticationError(message)

            # JSON with neither success nor a recognised error: treat the
            # absence of an explicit success as a failure.
            raise HumbleAuthenticationError(
                "Login failed: unexpected response from Humble Bundle."
            )

        # No JSON body to trust: fall back to HTTP status semantics.
        if response.status_code == 401:
            raise HumbleAuthenticationError("Invalid email or password.")
        if not response.ok:
            raise HumbleAuthenticationError(
                f"Login failed with status {response.status_code}."
            )
        raise HumbleAuthenticationError(
            "Login failed: Humble Bundle returned no confirmation."
        )

    def list_orders(self) -> List[HumbleOrder]:
        """
        Return all orders in the user's library.

        Returns
        -------
        list of HumbleOrder
        """
        try:
            response = self.session.get(LIBRARY_URL, timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            raise HumbleRequestError(
                "Timed out fetching the Humble Bundle library."
            ) from exc
        response.raise_for_status()
        data = response.json()

        orders: List[HumbleOrder] = []
        for item in data:
            gamekey = item.get("gamekey")
            product = item.get("human_name") or item.get("product", "")
            if not gamekey:
                continue
            orders.append(HumbleOrder(gamekey=gamekey, product=product))
        return orders

    def get_order_details(self, order_id: str) -> Dict[str, Any]:
        """
        Fetch the full JSON representation for an order.

        Parameters
        ----------
        order_id:
            Game key / order identifier.
        """
        url = ORDER_URL_TEMPLATE.format(order_id=order_id)
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            raise HumbleRequestError(
                f"Timed out fetching order {order_id}."
            ) from exc
        response.raise_for_status()
        return response.json()

