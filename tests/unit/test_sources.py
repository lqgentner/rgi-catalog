"""Tests for the pinned upstream sources."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import override

import pytest

from rgi_catalog.sources import SourceMismatchError, SourcePin, fetch, load_pins, verify

PAYLOAD = bytes(range(256)) * 64


def _pin(data: bytes, url: str = "http://unused.invalid/f.zip") -> SourcePin:
    return SourcePin(
        key="G",
        url=url,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        filename="f.zip",
    )


@dataclass
class _Server:
    url: str
    requests: list[str] = field(default_factory=list)
    truncate: bool = False


@pytest.fixture
def server() -> Iterator[_Server]:
    state = _Server(url="")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            body = PAYLOAD[: len(PAYLOAD) // 2] if state.truncate else PAYLOAD
            self.wfile.write(body)

        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}/f.zip"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield state
    httpd.shutdown()
    httpd.server_close()


def test_verify_accepts_matching_file(tmp_path: Path) -> None:
    path = tmp_path / "f.zip"
    path.write_bytes(PAYLOAD)
    verify(path, _pin(PAYLOAD))


def test_verify_rejects_size_and_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "f.zip"
    path.write_bytes(PAYLOAD[:-1])
    with pytest.raises(SourceMismatchError, match="size"):
        verify(path, _pin(PAYLOAD))
    changed = bytearray(PAYLOAD)
    changed[0] ^= 0xFF
    path.write_bytes(bytes(changed))
    with pytest.raises(SourceMismatchError, match="sha256"):
        verify(path, _pin(PAYLOAD))


def test_fetch_refuses_truncated_download_and_leaves_no_verified_file(
    tmp_path: Path,
    server: _Server,
) -> None:
    server.truncate = True
    with pytest.raises(SourceMismatchError):
        fetch(_pin(PAYLOAD, server.url), cache_dir=tmp_path)
    assert not (tmp_path / "f.zip").exists()
    assert not (tmp_path / "f.zip.part").exists()


def test_fetch_downloads_and_verifies(tmp_path: Path, server: _Server) -> None:
    path = fetch(_pin(PAYLOAD, server.url), cache_dir=tmp_path)
    assert path == tmp_path / "f.zip"
    assert path.read_bytes() == PAYLOAD


def test_fetch_reuses_verified_cache(tmp_path: Path, server: _Server) -> None:
    pin = _pin(PAYLOAD, server.url)
    fetch(pin, cache_dir=tmp_path)
    fetch(pin, cache_dir=tmp_path)
    assert len(server.requests) == 1


def test_load_pins_has_all_keys() -> None:
    pins = load_pins("7.0")
    assert set(pins) == {"G", "C", "I", "L", "regions", "rgi6_links"}
    for key, pin in pins.items():
        assert pin.key == key
        assert pin.url.startswith("https://")
        assert len(pin.sha256) == 64
        assert pin.size > 0
        assert pin.filename == pin.url.rsplit("/", 1)[1]
