"""Tests for the build record."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from rgi_catalog import record

if TYPE_CHECKING:
    from pathlib import Path


def test_checksum_is_multihash_sha256(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"glacier")
    assert record.checksum(path) == "1220" + hashlib.sha256(b"glacier").hexdigest()


def test_keep_updated_when_nothing_else_changed() -> None:
    old = {"updated": "2026-10-22T10:00:00Z", "files": {"a": 1}}
    new = {"updated": "2026-10-23T10:00:00Z", "files": {"a": 1}}
    assert record.merge_updated(old, new)["updated"] == "2026-10-22T10:00:00Z"


def test_new_updated_when_something_changed() -> None:
    old = {"updated": "2026-10-22T10:00:00Z", "files": {"a": 1}}
    new = {"updated": "2026-10-23T10:00:00Z", "files": {"a": 2}}
    assert record.merge_updated(old, new)["updated"] == "2026-10-23T10:00:00Z"
    assert record.merge_updated(None, new)["updated"] == "2026-10-23T10:00:00Z"
