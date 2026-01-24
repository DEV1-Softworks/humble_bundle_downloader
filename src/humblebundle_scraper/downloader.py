"""
Download orchestration for Humble Bundle orders.

This module focuses on:

- Enumerating downloadable files for each order.
- Skipping orders or subproducts that only contain keys (no files).
- Downloading all formats for each available asset.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .client import HumbleClient, HumbleOrder


@dataclass
class DownloadFile:
    """Metadata for a single downloadable file."""

    url: str
    filename: str
    subproduct_name: str
    platform: str


def _sanitize_filename(name: str) -> str:
    """Return a filesystem-safe filename."""
    safe = "".join(c for c in name if c not in '\\/:*?"<>|\n\r\t')
    return safe.strip() or "download"


def iter_downloadable_files(order_json: Dict[str, Any]) -> Iterable[DownloadFile]:
    """
    Yield all downloadable files for a given order JSON.

    Orders or subproducts that have no files are effectively skipped, which
    covers CD keys or license-only items.
    """
    subproducts: List[Dict[str, Any]] = order_json.get("subproducts", [])

    for sub in subproducts:
        sub_name = sub.get("human_name") or sub.get("machine_name") or "unknown"
        downloads = sub.get("downloads") or []

        for download in downloads:
            platform = download.get("platform") or "unknown"
            download_struct = download.get("download_struct") or []

            for struct in download_struct:
                url_info = struct.get("url") or {}
                web_url = url_info.get("web")
                if not web_url:
                    continue

                # Use provided name if any, otherwise derive from URL.
                file_name = struct.get("name") or os.path.basename(web_url)
                if not file_name:
                    file_name = "download"

                yield DownloadFile(
                    url=web_url,
                    filename=_sanitize_filename(file_name),
                    subproduct_name=sub_name,
                    platform=platform,
                )


def build_target_path(
    base_dir: Path, order: HumbleOrder, file: DownloadFile
) -> Path:
    """
    Build the output path for a single downloadable file.

    The layout is:

    <base_dir>/<order_product>/<subproduct_name>/<platform>/<filename>
    """
    parts: Tuple[str, ...] = (
        _sanitize_filename(order.product),
        _sanitize_filename(file.subproduct_name),
        _sanitize_filename(file.platform),
    )
    folder = base_dir.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / file.filename


def download_file(client: HumbleClient, url: str, target_path: Path) -> None:
    """
    Download a single file to the given path, skipping if it already exists.
    """
    if target_path.exists():
        return

    with client.session.get(url, stream=True) as response:
        response.raise_for_status()
        with target_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                fh.write(chunk)


def download_all_orders(
    client: HumbleClient, output_dir: Path, orders: Optional[List[HumbleOrder]] = None
) -> None:
    """
    Download all available files for the user's orders.

    Parameters
    ----------
    client:
        Authenticated HumbleClient instance.
    output_dir:
        Base directory where downloads will be stored.
    orders:
        Optional pre-fetched list of orders. If omitted, they are fetched
        via ``client.list_orders()``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    orders = orders if orders is not None else client.list_orders()

    for order in orders:
        order_json = client.get_order_details(order.gamekey)
        for file in iter_downloadable_files(order_json):
            path = build_target_path(output_dir, order, file)
            download_file(client, file.url, path)

