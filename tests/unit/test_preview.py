"""Tests for the local preview."""

from __future__ import annotations

from collections.abc import Iterator
import threading
from typing import TYPE_CHECKING
import urllib.request

import pytest

from rgi_catalog import preview

if TYPE_CHECKING:
    from pathlib import Path

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
}


@pytest.fixture
def served(tmp_path: Path) -> Iterator[str]:
    (tmp_path / "data.bin").write_bytes(bytes(range(100)))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "doc.json").write_text('{"a": 1}')
    server = preview.serve(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _request(
    url: str, method: str = "GET", headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, method=method, headers=headers or {})  # noqa: S310
    with urllib.request.urlopen(req) as response:  # noqa: S310
        return response.status, dict(response.headers), response.read()


def test_range_request_returns_exact_bytes(served: str) -> None:
    status, headers, body = _request(f"{served}/data.bin", headers={"Range": "bytes=10-19"})
    assert status == 206
    assert body == bytes(range(10, 20))
    assert headers["Content-Range"] == "bytes 10-19/100"
    assert headers["Content-Length"] == "10"
    assert headers["Accept-Ranges"] == "bytes"


def test_suffix_range_returns_the_tail(served: str) -> None:
    status, _, body = _request(f"{served}/data.bin", headers={"Range": "bytes=-5"})
    assert status == 206
    assert body == bytes(range(95, 100))


def test_head_content_length_exact(served: str) -> None:
    status, headers, body = _request(f"{served}/data.bin", method="HEAD")
    assert status == 200
    assert headers["Content-Length"] == "100"
    assert body == b""


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_cors_headers_on_get_head_options(served: str, method: str) -> None:
    _, headers, _ = _request(f"{served}/sub/doc.json", method=method)
    for key, value in CORS.items():
        assert headers[key] == value


def test_json_content_type(served: str) -> None:
    _, headers, body = _request(f"{served}/sub/doc.json")
    assert headers["Content-Type"] == "application/json"
    assert body == b'{"a": 1}'


def test_assemble_joins_both_trees(tmp_path: Path) -> None:
    catalog, staging = tmp_path / "catalog", tmp_path / "staging"
    (catalog / "v7.0" / "glaciers").mkdir(parents=True)
    (catalog / "v7.0" / "glaciers" / "collection.json").write_text("{}")
    (staging / "v7.0" / "glaciers").mkdir(parents=True)
    (staging / "v7.0" / "glaciers" / "rgi7.0-glaciers.parquet").write_bytes(b"PAR1")
    (staging / "v7.0" / ".reports").mkdir()
    (staging / "v7.0" / ".reports" / "fixes.json").write_text("[]")
    out = preview.assemble_preview(catalog, staging, tmp_path / "preview")
    assert (out / "v7.0" / "glaciers" / "collection.json").read_text() == "{}"
    assert (out / "v7.0" / "glaciers" / "rgi7.0-glaciers.parquet").read_bytes() == b"PAR1"
    assert not (out / "v7.0" / ".reports").exists()


def test_assemble_refuses_overlap(tmp_path: Path) -> None:
    catalog, staging = tmp_path / "catalog", tmp_path / "staging"
    for root in (catalog, staging):
        (root / "v7.0").mkdir(parents=True)
        (root / "v7.0" / "catalog.json").write_text("{}")
    with pytest.raises(preview.PreviewOverlapError, match=r"v7\.0/catalog\.json"):
        preview.assemble_preview(catalog, staging, tmp_path / "preview")
