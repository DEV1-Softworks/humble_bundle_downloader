"""
Tests for humblebundle_scraper.downloader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
import requests

from src.client import HumbleClient, HumbleOrder, HumbleRequestError
from src.downloader import (
    DownloadFile,
    _sanitize_path_component,
    build_target_path,
    download_all_orders,
    download_file,
    iter_downloadable_files,
    product_display_name,
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


def _df(url: str, name: str = "book.pdf", size=None) -> DownloadFile:
    return DownloadFile(
        url=url,
        filename=name,
        subproduct_name="Sub",
        platform="ebook",
        expected_size=size,
    )


def test_filename_is_derived_from_url_path_not_query_string() -> None:
    # Signed Humble URLs carry a query string that must not leak into
    # the filename (audit point 6).
    order_json = {
        "subproducts": [
            {
                "human_name": "Book",
                "downloads": [
                    {
                        "platform": "ebook",
                        "download_struct": [
                            {
                                "url": {
                                    "web": "https://dl.example.com/path/awesome-book.pdf?gamekey=abc&ttl=999&sig=xyz"
                                },
                                "file_size": 1234,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    files = list(iter_downloadable_files(order_json))
    assert len(files) == 1
    assert files[0].filename == "awesome-book.pdf"
    assert files[0].expected_size == 1234


def test_extension_derived_when_name_is_a_format_label() -> None:
    # Real Humble JSON uses "name" as a format label ("PDF", "EPUB"),
    # not a filename. The extension must still end up on disk: from the
    # URL path when present, else derived from the label.
    order_json = {
        "subproducts": [
            {
                "human_name": "Awesome Ebook",
                "downloads": [
                    {
                        "platform": "ebook",
                        "download_struct": [
                            {
                                "name": "PDF",
                                "url": {
                                    "web": "https://dl.example.com/files/awesome-book.pdf?ttl=9&sig=z"
                                },
                            },
                            {
                                "name": "EPUB",
                                "url": {"web": "https://dl.example.com/files/noext?ttl=9"},
                            },
                            {
                                "name": "PDF (HD)",
                                "url": {"web": "https://dl.example.com/files/blob"},
                            },
                        ],
                    }
                ],
            }
        ]
    }
    files = sorted(iter_downloadable_files(order_json), key=lambda f: f.filename)
    names = [f.filename for f in files]
    assert names == ["awesome-book.pdf", "blob.pdf", "noext.epub"]


def test_product_display_name_falls_back_to_gamekey() -> None:
    assert product_display_name({}, "key123") == "key123"
    assert (
        product_display_name({"product": {"human_name": "My Bundle"}}, "key123")
        == "My Bundle"
    )


def test_sanitize_path_component_blocks_traversal() -> None:
    assert _sanitize_path_component("..") == "download"
    assert _sanitize_path_component(".") == "download"
    assert _sanitize_path_component("../../etc/passwd") == "etcpasswd"
    assert _sanitize_path_component("  ..hidden  ") == "hidden"


def test_download_file_timeout_raises_request_error(tmp_path: Path) -> None:
    client = HumbleClient()
    client.session.get = MagicMock(side_effect=requests.Timeout())  # type: ignore[assignment]

    target = tmp_path / "book.pdf"

    with pytest.raises(HumbleRequestError, match="Timed out downloading"):
        download_file(client, _df("https://example.com/book.pdf"), target)

    # Neither the final file nor a .part stub should be left behind.
    assert not target.exists()
    assert not target.with_name("book.pdf.part").exists()


def test_download_file_skips_when_size_matches(tmp_path: Path) -> None:
    client = HumbleClient()
    client.session.get = MagicMock()  # type: ignore[assignment]

    target = tmp_path / "book.pdf"
    target.write_bytes(b"1234")  # 4 bytes

    did_download = download_file(
        client, _df("https://example.com/book.pdf", size=4), target
    )

    assert did_download is False
    client.session.get.assert_not_called()  # type: ignore[union-attr]


def test_download_file_redownloads_on_size_mismatch(tmp_path: Path) -> None:
    client = HumbleClient()
    response_mock = MagicMock()
    response_mock.__enter__.return_value = response_mock
    response_mock.iter_content.return_value = [b"full-content"]
    response_mock.raise_for_status.return_value = None
    client.session.get = MagicMock(return_value=response_mock)  # type: ignore[assignment]

    target = tmp_path / "book.pdf"
    target.write_bytes(b"xx")  # wrong size -> stale partial from prior run

    did_download = download_file(
        client,
        _df("https://example.com/book.pdf", size=len(b"full-content")),
        target,
    )

    assert did_download is True
    assert target.read_bytes() == b"full-content"


def test_download_all_orders_continues_after_failed_order(
    tmp_path: Path,
) -> None:
    client = HumbleClient()
    orders = [
        HumbleOrder(gamekey="bad", product=""),
        HumbleOrder(gamekey="good", product=""),
    ]
    client.list_orders = MagicMock(return_value=orders)  # type: ignore[assignment]
    client.get_order_details = MagicMock(  # type: ignore[assignment]
        side_effect=[
            HumbleRequestError("boom"),
            make_order_json_with_downloads(),
        ]
    )

    response_mock = MagicMock()
    response_mock.__enter__.return_value = response_mock
    response_mock.iter_content.return_value = [b"data"]
    response_mock.raise_for_status.return_value = None
    client.session.get = MagicMock(return_value=response_mock)  # type: ignore[assignment]

    # Should not raise even though the first order errors out.
    download_all_orders(client, tmp_path, request_delay=0)

    # The good order's two files were still downloaded.
    assert client.session.get.call_count == 2  # type: ignore[union-attr]


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

    download_all_orders(client, tmp_path, request_delay=0)

    # Two files should have been requested.
    assert client.session.get.call_count == 2  # type: ignore[union-attr]

