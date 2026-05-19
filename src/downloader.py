"""
Download orchestration for Humble Bundle orders.

This module focuses on:

- Enumerating downloadable files for each order.
- Skipping orders or subproducts that only contain keys (no files).
- Downloading all formats for each available asset, atomically and with
  retries, while being polite to Humble Bundle's servers.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

from .client import HumbleClient, HumbleOrder, HumbleRequestError

logger = logging.getLogger(__name__)

# (connect timeout, read timeout). The read timeout is the maximum gap
# allowed *between* received chunks, not a cap on total download time, so
# a generous value still works for large files while a stalled socket
# fails fast instead of hanging forever.
DOWNLOAD_TIMEOUT = (10, 60)

# Politeness: seconds to wait between successive HTTP requests so the
# scraper does not hammer Humble Bundle and risk an IP ban.
DEFAULT_REQUEST_DELAY = 1.0

# How many times to retry a single file before giving up on it.
DEFAULT_MAX_RETRIES = 3


@dataclass
class DownloadFile:
    """Metadata for a single downloadable file."""

    url: str
    filename: str
    subproduct_name: str
    platform: str
    expected_size: Optional[int] = None


def _sanitize_path_component(name: str) -> str:
    """
    Return a filesystem-safe single path component.

    Strips characters illegal on common filesystems, removes control
    characters, collapses whitespace, and refuses values that would
    traverse the directory tree (``.``, ``..``, leading dots).
    """
    # Drop reserved/illegal characters and control codes.
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    # Collapse internal whitespace runs to a single space.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Strip leading dots so "." / ".." / hidden-traversal cannot occur.
    cleaned = cleaned.lstrip(".").strip()
    if not cleaned or cleaned in {".", ".."}:
        return "download"
    return cleaned


def _filename_from_url(web_url: str) -> str:
    """
    Derive a clean filename from a (possibly signed) download URL.

    Humble's URLs are signed, e.g. ``.../book.pdf?gamekey=...&ttl=...``;
    using the raw URL would embed the query string in the filename, so
    only the path component's basename is used.
    """
    path = urlparse(web_url).path
    return unquote(os.path.basename(path))


def _has_extension(name: str) -> bool:
    """Return ``True`` if ``name`` ends in a non-empty file extension."""
    return bool(os.path.splitext(name)[1])


def _ext_from_format_label(label: str) -> str:
    """
    Turn a Humble format label into a file extension.

    Humble's ``download_struct[].name`` is usually a format label such as
    ``"PDF"``, ``"EPUB"``, ``"MOBI"`` or ``"PDF (HD)"`` rather than a real
    filename. The first alphanumeric token is used so ``"PDF (HD)"`` maps
    to ``.pdf``. Returns ``""`` when no usable token is found.
    """
    match = re.search(r"[A-Za-z0-9]+", label or "")
    return f".{match.group(0).lower()}" if match else ""


def _resolve_filename(
    struct: Dict[str, Any], web_url: str, subproduct_name: str
) -> str:
    """
    Decide the on-disk filename (with extension) for a download.

    Resolution order:

    1. An explicit ``name`` that already carries an extension is trusted
       as-is (e.g. ``"awesome-book.epub"``).
    2. Otherwise the URL path basename is used when it has an extension
       (Humble's signed URLs point at the real file, e.g. ``book.pdf``).
    3. Otherwise the explicit ``name`` is treated as a *format label*
       (``"PDF"``, ``"EPUB"``, ...) and turned into an extension, applied
       to the URL basename or the subproduct name as the stem.
    """
    explicit = (struct.get("name") or "").strip()
    url_name = _filename_from_url(web_url)

    if explicit and _has_extension(explicit):
        return explicit
    if url_name and _has_extension(url_name):
        return url_name

    stem = os.path.splitext(url_name)[0] or subproduct_name or "download"
    ext = _ext_from_format_label(explicit)
    return f"{stem}{ext}" if ext else stem


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

                # Resolve a filename that always carries an extension:
                # Humble's struct "name" is typically a format label
                # ("PDF", "EPUB"), not a real filename.
                file_name = _resolve_filename(struct, web_url, sub_name)
                if not file_name:
                    file_name = "download"

                size = struct.get("file_size")
                try:
                    expected_size = int(size) if size is not None else None
                except (TypeError, ValueError):
                    expected_size = None

                yield DownloadFile(
                    url=web_url,
                    filename=_sanitize_path_component(file_name),
                    subproduct_name=sub_name,
                    platform=platform,
                    expected_size=expected_size,
                )


def product_display_name(order_json: Dict[str, Any], fallback: str) -> str:
    """
    Return the human-readable product/bundle name for an order.

    The library listing endpoint does not include the product name; it
    only lives in the per-order detail JSON under ``product``. ``fallback``
    (typically the gamekey) is used when it is absent.
    """
    product = order_json.get("product") or {}
    name = product.get("human_name") or product.get("machine_name")
    return name or fallback


def build_target_path(
    base_dir: Path, order: HumbleOrder, file: DownloadFile
) -> Path:
    """
    Build the output path for a single downloadable file.

    The layout is:

    <base_dir>/<order_product>/<subproduct_name>/<platform>/<filename>
    """
    parts: Tuple[str, ...] = (
        _sanitize_path_component(order.product or order.gamekey),
        _sanitize_path_component(file.subproduct_name),
        _sanitize_path_component(file.platform),
    )
    folder = base_dir.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / file.filename


def _is_already_complete(target_path: Path, expected_size: Optional[int]) -> bool:
    """
    Return ``True`` only if the file exists *and* matches the expected
    size. A size mismatch means a previous run was interrupted, so the
    file must be downloaded again instead of being trusted.
    """
    if not target_path.exists():
        return False
    if expected_size is None:
        return True
    return target_path.stat().st_size == expected_size


def download_file(
    client: HumbleClient, file: DownloadFile, target_path: Path
) -> bool:
    """
    Download ``file`` to ``target_path`` atomically.

    The data is streamed to a ``.part`` sibling file and only renamed
    into place once the full body (and, when known, the expected size)
    has been received, so an interrupted run never leaves a truncated
    file that looks complete.

    Returns ``True`` if a download happened, ``False`` if it was skipped
    because a valid copy already exists.
    """
    if _is_already_complete(target_path, file.expected_size):
        logger.info("Skipping (already downloaded): %s", target_path.name)
        return False

    part_path = target_path.with_name(target_path.name + ".part")
    try:
        with client.session.get(
            file.url, stream=True, timeout=DOWNLOAD_TIMEOUT
        ) as response:
            response.raise_for_status()
            with part_path.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    fh.write(chunk)

        if (
            file.expected_size is not None
            and part_path.stat().st_size != file.expected_size
        ):
            actual = part_path.stat().st_size
            part_path.unlink(missing_ok=True)
            raise HumbleRequestError(
                f"Size mismatch for {target_path.name}: "
                f"expected {file.expected_size} bytes, got {actual}."
            )

        os.replace(part_path, target_path)
        logger.info("Downloaded: %s", target_path.name)
        return True
    except requests.Timeout as exc:
        part_path.unlink(missing_ok=True)
        raise HumbleRequestError(
            f"Timed out downloading {target_path.name}."
        ) from exc
    except requests.RequestException as exc:
        part_path.unlink(missing_ok=True)
        raise HumbleRequestError(
            f"Failed to download {target_path.name}: {exc}"
        ) from exc
    except BaseException:
        # Never leave a partial .part behind on Ctrl-C or unexpected error.
        part_path.unlink(missing_ok=True)
        raise


def _download_with_retry(
    client: HumbleClient,
    file: DownloadFile,
    target_path: Path,
    max_retries: int,
) -> bool:
    """
    Download a file, retrying transient failures with exponential
    backoff. Raises ``HumbleRequestError`` if all attempts fail.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return download_file(client, file, target_path)
        except HumbleRequestError as exc:
            last_exc = exc
            if attempt < max_retries:
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "Attempt %d/%d failed for %s (%s); retrying in %ds.",
                    attempt,
                    max_retries,
                    target_path.name,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
    assert last_exc is not None
    raise last_exc


def download_all_orders(
    client: HumbleClient,
    output_dir: Path,
    orders: Optional[List[HumbleOrder]] = None,
    request_delay: float = DEFAULT_REQUEST_DELAY,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> None:
    """
    Download all available files for the user's orders.

    A failure on one order or one file is logged and skipped instead of
    aborting the whole run, and a small delay is inserted between
    requests to stay within polite usage of Humble Bundle.

    Parameters
    ----------
    client:
        Authenticated HumbleClient instance.
    output_dir:
        Base directory where downloads will be stored.
    orders:
        Optional pre-fetched list of orders. If omitted, they are fetched
        via ``client.list_orders()``.
    request_delay:
        Seconds to pause between HTTP requests.
    max_retries:
        Attempts per file before it is skipped.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    orders = orders if orders is not None else client.list_orders()

    total = len(orders)
    for index, order in enumerate(orders, start=1):
        try:
            order_json = client.get_order_details(order.gamekey)
        except HumbleRequestError as exc:
            logger.error(
                "Skipping order %s (%d/%d): %s",
                order.gamekey,
                index,
                total,
                exc,
            )
            continue

        # The product name is only available here, not in list_orders().
        order.product = product_display_name(order_json, order.gamekey)
        logger.info(
            "Processing order %d/%d: %s", index, total, order.product
        )

        for file in iter_downloadable_files(order_json):
            path = build_target_path(output_dir, order, file)
            try:
                downloaded = _download_with_retry(
                    client, file, path, max_retries
                )
            except HumbleRequestError as exc:
                logger.error("Giving up on %s: %s", path.name, exc)
                continue

            if downloaded and request_delay > 0:
                time.sleep(request_delay)

        if request_delay > 0:
            time.sleep(request_delay)
