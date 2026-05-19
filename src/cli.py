"""
Command-line interface for the Humble Bundle downloader.
"""

from __future__ import annotations

import getpass
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .client import HumbleClient, HumbleAuthenticationError, TwoFactorRequiredError
from .downloader import (
    DEFAULT_FAILURE_REPORT_NAME,
    DEFAULT_REQUEST_DELAY,
    download_all_orders,
)


@dataclass
class Config:
    """Runtime configuration loaded from the environment."""

    session_cookie: Optional[str]
    session_file: Path
    output_dir: Path
    request_delay: float
    failure_report: Path


def load_config() -> Config:
    """
    Load configuration from environment variables.

    The password is intentionally *not* loaded here: it is only
    requested interactively as a last resort when no usable session is
    available, so it never has to be stored at rest.
    """
    load_dotenv()
    try:
        delay = float(
            os.getenv("HUMBLE_REQUEST_DELAY", str(DEFAULT_REQUEST_DELAY))
        )
    except ValueError:
        delay = DEFAULT_REQUEST_DELAY
    output_dir = Path(os.getenv("HUMBLE_DOWNLOAD_DIR", "downloads"))
    failure_report = Path(
        os.getenv(
            "HUMBLE_FAILURE_REPORT",
            str(output_dir / DEFAULT_FAILURE_REPORT_NAME),
        )
    )
    return Config(
        session_cookie=os.getenv("HUMBLE_SESSION_COOKIE") or None,
        session_file=Path(
            os.getenv("HUMBLE_SESSION_FILE", ".humble_session.json")
        ),
        output_dir=output_dir,
        request_delay=max(0.0, delay),
        failure_report=failure_report,
    )


def _password_login(client: HumbleClient) -> None:
    """Interactive email/password (+ optional 2FA) login fallback."""
    email = os.getenv("HUMBLE_EMAIL", "") or input(
        "Humble Bundle email: "
    ).strip()
    password = getpass.getpass("Humble Bundle password: ")
    otp = os.getenv("HUMBLE_2FA_CODE") or None

    try:
        client.login(email=email, password=password, otp=otp)
    except TwoFactorRequiredError:
        code = getpass.getpass("Enter Humble Bundle 2FA code: ")
        client.login(email=email, password=password, otp=code)


def main() -> None:
    """
    Entry point for the CLI.

    Authentication order of preference:

    1. A previously saved session file (no secret entered).
    2. A ``HUMBLE_SESSION_COOKIE`` copied from a logged-in browser.
    3. Interactive password login (the session is then saved so the
       password is not needed again).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config()
    client = HumbleClient(session_file=config.session_file)

    if config.session_cookie:
        client.set_session_cookie(config.session_cookie)

    try:
        if not client.is_authenticated():
            _password_login(client)
    except HumbleAuthenticationError as exc:
        raise SystemExit(f"Authentication failed: {exc}") from exc

    if not client.is_authenticated():
        raise SystemExit(
            "Authentication failed: session is not valid. Provide a fresh "
            "HUMBLE_SESSION_COOKIE or log in with email/password."
        )

    # Make sure a valid cookie session is persisted for next time.
    client.save_session()

    download_all_orders(
        client,
        config.output_dir,
        request_delay=config.request_delay,
        failure_report=config.failure_report,
    )


if __name__ == "__main__":
    main()

