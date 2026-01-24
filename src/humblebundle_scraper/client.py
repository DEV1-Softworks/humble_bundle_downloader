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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


LOGIN_URL = "https://www.humblebundle.com/processlogin"
LIBRARY_URL = "https://www.humblebundle.com/api/v1/user/order"
ORDER_URL_TEMPLATE = "https://www.humblebundle.com/api/v1/order/{order_id}?all_tiers=true&wallet=true"


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

    def __init__(self) -> None:
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
        payload: Dict[str, Any] = {
            "username": email,
            "password": password,
            "rememberme": "on",
        }
        if otp:
            payload["code"] = otp

        response = self.session.post(LOGIN_URL, data=payload)

        if response.status_code == 401:
            # Heuristic: treat any 401 with two‑factor wording as a 2FA requirement.
            body = response.text.lower()
            if "two-factor" in body or "2fa" in body or "otp" in body:
                raise TwoFactorRequiredError("Two-factor authentication code required.")
            raise HumbleAuthenticationError("Invalid email or password.")

        if not response.ok:
            raise HumbleAuthenticationError(
                f"Login failed with status {response.status_code}."
            )

    def list_orders(self) -> List[HumbleOrder]:
        """
        Return all orders in the user's library.

        Returns
        -------
        list of HumbleOrder
        """
        response = self.session.get(LIBRARY_URL)
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
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

