"""Tests for the build record."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

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


def _report(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    path = tmp_path / "fixes.json"
    path.write_text(json.dumps(entries))
    return path


def test_fix_counts_from_report(tmp_path: Path) -> None:
    path = _report(
        tmp_path,
        [
            {"fix": "text-encoding", "product": "glaciers", "column": "glac_name", "count": 2,
             "ids": ["a", "b"]},
            {"fix": "drop-z", "product": "glaciers", "column": "geometry", "count": 3, "ids": []},
            {"fix": "drop-z", "product": "regions", "column": "geometry", "count": 0, "ids": []},
        ],
    )  # fmt: skip
    assert record.fix_counts(path, ["glaciers", "regions"]) == {
        "glaciers": [
            {"fix": "text-encoding", "column": "glac_name", "count": 2},
            {"fix": "drop-z", "column": "geometry", "count": 3},
        ],
        "regions": [{"fix": "drop-z", "column": "geometry", "count": 0}],
    }


def test_fix_counts_refuse_a_partial_report(tmp_path: Path) -> None:
    # A convert of some products writes a report of those products only.
    path = _report(
        tmp_path,
        [{"fix": "drop-z", "product": "glaciers", "column": "geometry", "count": 3, "ids": []}],
    )
    with pytest.raises(ValueError, match="regions"):
        record.fix_counts(path, ["glaciers", "regions"])
