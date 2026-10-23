"""Tests for the convert step."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

from rgi_catalog import pipeline

if TYPE_CHECKING:
    from pathlib import Path

    from tests.unit.conftest import FakeRGI


def test_convert_glaciers_on_fixture(
    fake_rgi: FakeRGI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {
        "G": fake_rgi.g_zip,
        "C": fake_rgi.c_zip,
        "rgi6_links": fake_rgi.rgi6_links,
    }

    def fake_source_files(version: str) -> dict[str, tuple[Path, str]]:
        assert version == "7.0"
        return {k: (v, f"sha-{k}") for k, v in files.items()}

    monkeypatch.setattr(pipeline, "source_files", fake_source_files)
    staging = tmp_path / "staging"
    result = pipeline.convert("7.0", ["glaciers"], staging=staging)

    out = staging / "v7.0" / "glaciers" / "rgi7.0-glaciers.parquet"
    assert result.paths == {"glaciers": out}
    assert result.row_counts == {"glaciers": 3}
    assert pq.ParquetFile(out).metadata.num_rows == 3
    footer = {k.decode(): v.decode() for k, v in pq.ParquetFile(out).metadata.metadata.items()}
    assert footer["rgi:version"] == "7.0"
    assert json.loads(footer["rgi:sources"]) == {
        fake_rgi.g_zip.name: "sha-G",
        fake_rgi.c_zip.name: "sha-C",
        fake_rgi.rgi6_links.name: "sha-rgi6_links",
    }

    report = json.loads((staging / "v7.0" / ".reports" / "fixes.json").read_text())
    by_fix = {(r["fix"], r["column"]): r for r in report}
    assert by_fix["drop-z", "geometry"]["count"] == 1
    assert by_fix["text-encoding", "glac_name"]["count"] == 1
    assert by_fix["text-encoding", "glac_name"]["ids"] == ["RGI2000-v7.0-G-08-00001"]
    assert all(r["product"] == "glaciers" for r in report)
    assert [f.fix for f in result.fixes] == [r["fix"] for r in report]


def test_convert_refuses_unknown_product(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nonsense"):
        pipeline.convert("7.0", ["nonsense"], staging=tmp_path)


def test_convert_every_product_on_fixture(
    fake_rgi: FakeRGI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {
        "G": fake_rgi.g_zip,
        "C": fake_rgi.c_zip,
        "L": fake_rgi.l_zip,
        "I": fake_rgi.i_zip,
        "regions": fake_rgi.regions_zip,
        "rgi6_links": fake_rgi.rgi6_links,
    }

    def fake_source_files(version: str) -> dict[str, tuple[Path, str]]:
        assert version == "7.0"
        return {k: (v, f"sha-{k}") for k, v in files.items()}

    monkeypatch.setattr(pipeline, "source_files", fake_source_files)
    staging = tmp_path / "staging"
    result = pipeline.convert("7.0", list(pipeline.BUILDERS), staging=staging)
    assert result.row_counts == {
        "glaciers": 3,
        "complexes": 2,
        "centerlines": 3,
        "intersects": 1,
        "regions": 6,
    }
    footer = pq.ParquetFile(result.paths["regions"]).metadata.metadata
    assert json.loads(footer[b"rgi:sources"]) == {fake_rgi.regions_zip.name: "sha-regions"}
    report = json.loads((staging / "v7.0" / ".reports" / "fixes.json").read_text())
    assert {r["product"] for r in report} == set(pipeline.BUILDERS)
