"""
Tests for humblebundle_scraper.downloader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

from humblebundle_scraper.client import HumbleClient, HumbleOrder
from humblebundle_scraper.downloader import (
    DownloadFile,
    build_target_path,
    download_all_orders,
    iter_downloadable_files,
)


def make_order_json_with_downloads() -> Dict[str, Any]:
    """Return a minimal order JSON structure with downloadable files."""
    return {
        "subproducts": [
            {
                "human_name": "Awesome Ebook",
                "downloads": [
                    {
                        "platform": "ebook",
                        "download_struct": [
                            {
                                "name": "awesome-book.epub",
                                "url": {"web": "https://download.example.com/awesome-book.epub"},
                            },
                            {
                                "name": "awesome-book.pdf",
                                "url": {"web": "https://download.example.com/awesome-book.pdf"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def make_order_json_keys_only() -> Dict[str, Any]:
    """Return an order JSON structure with no downloadable files."""
    return {"subproducts": [{"human_name": "Key Only Product", "downloads": []}]}


def test_iter_downloadable_files_yields_all_formats() -> None:
    order_json = make_order_json_with_downloads()
    files = list(iter_downloadable_files(order_json))

    assert len(files) == 2
    names = sorted(f.filename for f in files)
    assert names == ["awesome-book.epub", "awesome-book.pdf"]


def test_iter_downloadable_files_skips_key_only_orders() -> None:
    order_json = make_order_json_keys_only()
    files = list(iter_downloadable_files(order_json))

    assert files == []


def test_build_target_path_creates_nested_structure(tmp_path: Path) -> None:
    order = HumbleOrder(gamekey="123", product="My Bundle")
    download_file = DownloadFile(
        url="https://download.example.com/awesome-book.epub",
        filename="awesome-book.epub",
        subproduct_name="Awesome Ebook",
        platform="ebook",
    )

    path = build_target_path(tmp_path, order, download_file)

    # Path should be nested under the bundle, subproduct, and platform.
    assert path.parent.exists()
    assert "My Bundle" in str(path.parent)
    assert "Awesome Ebook" in str(path.parent)
    assert "ebook" in str(path.parent)


def test_download_all_orders_uses_client_for_each_file(tmp_path: Path, monkeypatch) -> None:
    # Prepare a fake client whose HTTP calls we do not execute.
    client = HumbleClient()
    client.list_orders = MagicMock()  # type: ignore[assignment]

    orders: List[HumbleOrder] = [HumbleOrder(gamekey="abc123", product="My Bundle")]
    client.list_orders.return_value = orders  # type: ignore[assignment]

    client.get_order_details = MagicMock(  # type: ignore[assignment]
        return_value=make_order_json_with_downloads()
    )

    # Mock the session.get used by download_file
    response_mock = MagicMock()
    response_mock.__enter__.return_value = response_mock
    response_mock.iter_content.return_value = [b"data"]
    response_mock.raise_for_status.return_value = None

    client.session.get = MagicMock(return_value=response_mock)  # type: ignore[assignment]

    download_all_orders(client, tmp_path)

    # Two files should have been requested.
    assert client.session.get.call_count == 2  # type: ignore[union-attr]

