"""
Command-line interface for the Humble Bundle downloader.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .client import HumbleClient, HumbleAuthenticationError, TwoFactorRequiredError
from .downloader import download_all_orders


def load_credentials() -> tuple[str, str, Optional[str], Path]:
    """
    Load credentials and configuration from environment variables.

    Returns
    -------
    (email, password, otp, output_dir)
    """
    load_dotenv()
    email = os.getenv("HUMBLE_EMAIL", "")
    password = os.getenv("HUMBLE_PASSWORD", "")
    otp = os.getenv("HUMBLE_2FA_CODE") or None
    output_dir = Path(os.getenv("HUMBLE_DOWNLOAD_DIR", "downloads"))

    if not email:
        email = input("Humble Bundle email: ").strip()
    if not password:
        password = getpass.getpass("Humble Bundle password: ")

    return email, password, otp, output_dir


def main() -> None:
    """
    Entry point for the CLI.
    """
    email, password, otp, output_dir = load_credentials()

    client = HumbleClient()

    try:
        client.login(email=email, password=password, otp=otp)
    except TwoFactorRequiredError:
        code = getpass.getpass("Enter Humble Bundle 2FA code: ")
        client.login(email=email, password=password, otp=code)
    except HumbleAuthenticationError as exc:
        raise SystemExit(f"Authentication failed: {exc}") from exc

    download_all_orders(client, output_dir)


if __name__ == "__main__":
    main()

