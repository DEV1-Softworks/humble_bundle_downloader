"""
Tests for humblebundle_scraper.downloader.
"""

from __future__ import annotations

import hashlib
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


def _df(url: str, name: str = "book.pdf", size=None, md5=None) -> DownloadFile:
    return DownloadFile(
        url=url,
        filename=name,
        subproduct_name="Sub",
        platform="ebook",
        expected_size=size,
        expected_md5=md5,
    )


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _streaming_response(chunks: list[bytes]) -> MagicMock:
    response_mock = MagicMock()
    response_mock.__enter__.return_value = response_mock
    response_mock.iter_content.return_value = chunks
    response_mock.raise_for_status.return_value = None
    return response_mock


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


def test_iter_downloadable_files_captures_md5() -> None:
    order_json = {
        "subproducts": [
            {
                "human_name": "Book",
                "downloads": [
                    {
                        "platform": "ebook",
                        "download_struct": [
                            {
                                "name": "PDF",
                                "md5": "  D41D8CD98F00B204E9800998ECF8427E  ",
                                "url": {"web": "https://dl.example.com/book.pdf"},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    files = list(iter_downloadable_files(order_json))
    # Whitespace trimmed and normalised to lowercase for comparison.
    assert files[0].expected_md5 == "d41d8cd98f00b204e9800998ecf8427e"


def test_download_file_skips_when_md5_matches(tmp_path: Path) -> None:
    client = HumbleClient()
    client.session.get = MagicMock()  # type: ignore[assignment]

    target = tmp_path / "book.pdf"
    target.write_bytes(b"the real bytes")

    did_download = download_file(
        client,
        _df("https://example.com/book.pdf", md5=_md5(b"the real bytes")),
        target,
    )

    assert did_download is False
    client.session.get.assert_not_called()  # type: ignore[union-attr]


def test_download_file_redownloads_on_md5_mismatch(tmp_path: Path) -> None:
    client = HumbleClient()
    good = b"the real bytes"
    client.session.get = MagicMock(  # type: ignore[assignment]
        return_value=_streaming_response([good])
    )

    target = tmp_path / "book.pdf"
    target.write_bytes(b"corrupted earlier run")  # right place, wrong content

    did_download = download_file(
        client, _df("https://example.com/book.pdf", md5=_md5(good)), target
    )

    assert did_download is True
    assert target.read_bytes() == good


def test_download_file_raises_on_md5_mismatch_after_download(
    tmp_path: Path,
) -> None:
    client = HumbleClient()
    client.session.get = MagicMock(  # type: ignore[assignment]
        return_value=_streaming_response([b"served bytes"])
    )

    target = tmp_path / "book.pdf"

    with pytest.raises(HumbleRequestError, match="MD5 mismatch"):
        download_file(
            client,
            _df("https://example.com/book.pdf", md5=_md5(b"expected bytes")),
            target,
        )

    # Corrupt download must not be left on disk (nor as a .part stub).
    assert not target.exists()
    assert not target.with_name("book.pdf.part").exists()


def test_download_file_keeps_file_on_size_mismatch_without_md5(
    tmp_path: Path,
) -> None:
    # Humble's file_size is unreliable; with no MD5 to confirm
    # corruption, a larger-than-expected body must be kept, not deleted.
    client = HumbleClient()
    served = b"actually a bit larger than humble claimed"
    client.session.get = MagicMock(  # type: ignore[assignment]
        return_value=_streaming_response([served])
    )

    target = tmp_path / "book.pdf"

    did_download = download_file(
        client,
        _df("https://example.com/book.pdf", size=5),  # wrong/stale size
        target,
    )

    assert did_download is True
    assert target.read_bytes() == served


def test_failed_download_is_written_to_failure_report(tmp_path: Path) -> None:
    # A file whose MD5 never verifies should be given up on and recorded
    # in the failure report so it can be fetched manually.
    client = HumbleClient()
    client.list_orders = MagicMock(  # type: ignore[assignment]
        return_value=[HumbleOrder(gamekey="abc", product="My Bundle")]
    )
    client.get_order_details = MagicMock(  # type: ignore[assignment]
        return_value={
            "product": {"human_name": "My Bundle"},
            "subproducts": [
                {
                    "human_name": "Book",
                    "downloads": [
                        {
                            "platform": "ebook",
                            "download_struct": [
                                {
                                    "name": "PDF",
                                    "md5": _md5(b"what humble promised"),
                                    "url": {
                                        "web": "https://dl.example.com/book.pdf?sig=xyz"
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    client.session.get = MagicMock(  # type: ignore[assignment]
        return_value=_streaming_response([b"corrupt bytes from CDN"])
    )

    report = tmp_path / "failures.log"
    download_all_orders(
        client,
        tmp_path,
        request_delay=0,
        max_retries=1,
        failure_report=report,
    )

    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "My Bundle" in content
    assert "https://dl.example.com/book.pdf?sig=xyz" in content
    assert _md5(b"what humble promised") in content
    assert "MD5 mismatch" in content


def test_failure_report_defaults_into_output_dir(tmp_path: Path) -> None:
    client = HumbleClient()
    client.list_orders = MagicMock(return_value=[])  # type: ignore[assignment]

    download_all_orders(client, tmp_path, request_delay=0)

    # No failures -> no report file is created, but the default path is
    # derived under the output directory (no crash, no stray file).
    assert not (tmp_path / "failed_downloads.log").exists()


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

