"""Tests for the glacier names table."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import geopandas as gpd
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point

from rgi_catalog import nametable
from rgi_catalog.geoparquet import KV_KEYS, write_geoparquet
from rgi_catalog.paths import STAGING
from rgi_catalog.pipeline import output_path

if TYPE_CHECKING:
    from pathlib import Path

GLACIERS_FILE = output_path(STAGING, "7.0", "glaciers")
NAMES_FILE = nametable.names_path(STAGING, "7.0")
COMPLEXES_FILE = output_path(STAGING, "7.0", "complexes")


def _glaciers(tmp_path: Path, n: int = 5) -> Path:
    gdf = gpd.GeoDataFrame(
        {
            "rgi_id": [f"RGI2000-v7.0-G-11-{i:05d}" for i in range(1, n + 1)],
            "o1region": ["11"] * n,
            "o2region": ["11-01"] * n,
            "area_km2": [float(i) for i in range(n)],
            "glac_name": ["CHEILON GLACIER DE", None, *["X"] * (n - 2)],
            "display_name": ["Glacier de Cheilon", None, *["X"] * (n - 2)],
        },
        geometry=[Point(7.0 + i / 100, 46.0) for i in range(n)],
        crs="EPSG:4326",
    )
    out = tmp_path / "glaciers.parquet"
    write_geoparquet(gdf, out, kv={k: f"value of {k}" for k in KV_KEYS}, order_by="rgi_id")
    return out


def test_names_table_has_the_columns_and_rows_of_the_glaciers(tmp_path: Path) -> None:
    glaciers = _glaciers(tmp_path)
    out = nametable.write_names_table(glaciers, tmp_path / "names.parquet")
    names = pq.read_table(out)
    assert tuple(names.column_names) == nametable.COLUMNS
    source = pq.read_table(glaciers, columns=list(nametable.COLUMNS))
    assert names.to_pylist() == source.to_pylist()


def test_names_table_is_plain_parquet_with_the_rgi_footer(tmp_path: Path) -> None:
    out = nametable.write_names_table(_glaciers(tmp_path), tmp_path / "names.parquet")
    footer = {k.decode(): v.decode() for k, v in pq.ParquetFile(out).metadata.metadata.items()}
    # Without the geo key, a reader takes it as a table, not as GeoParquet.
    assert "geo" not in footer
    assert {k: footer[k] for k in KV_KEYS} == {k: f"value of {k}" for k in KV_KEYS}


def test_names_table_uses_the_delta_encodings(tmp_path: Path) -> None:
    out = nametable.write_names_table(_glaciers(tmp_path), tmp_path / "names.parquet")
    group = pq.ParquetFile(out).metadata.row_group(0)
    encodings = {group.column(i).path_in_schema: group.column(i).encodings for i in range(5)}
    for column, encoding in nametable.ENCODINGS.items():
        assert encoding in encodings[column]
    for column in nametable.DICTIONARY:
        assert "RLE_DICTIONARY" in encodings[column]


def test_names_table_is_deterministic(tmp_path: Path) -> None:
    glaciers = _glaciers(tmp_path)
    first = nametable.write_names_table(glaciers, tmp_path / "a.parquet")
    second = nametable.write_names_table(glaciers, tmp_path / "b.parquet")
    assert (
        hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    )


def test_names_path_is_beside_the_glaciers_file(tmp_path: Path) -> None:
    path = nametable.names_path(tmp_path, "7.0")
    assert path == tmp_path / "v7.0" / "glaciers" / "rgi7.0-glacier-names.parquet"
    assert path.parent == output_path(tmp_path, "7.0", "glaciers").parent


@pytest.mark.skipif(not NAMES_FILE.exists(), reason="needs the staged names table")
def test_staged_names_table_follows_the_glaciers_file() -> None:
    names = pq.read_table(NAMES_FILE)
    glaciers = pq.read_table(GLACIERS_FILE, columns=list(nametable.COLUMNS))
    assert names.equals(glaciers.replace_schema_metadata(names.schema.metadata))
    glaciers_footer = pq.ParquetFile(GLACIERS_FILE).metadata.metadata
    names_footer = pq.ParquetFile(NAMES_FILE).metadata.metadata
    rgi_keys = [k.encode() for k in KV_KEYS]
    assert {k: names_footer[k] for k in rgi_keys} == {k: glaciers_footer[k] for k in rgi_keys}
    assert b"geo" not in names_footer
    assert json.loads(names_footer[b"rgi:sources"])


@pytest.mark.skipif(not COMPLEXES_FILE.exists(), reason="needs the staged complexes file")
def test_complex_numbers_run_without_gaps_in_each_region() -> None:
    # complexes/AGENTS.md states this, and clients test an ID against it.
    ids = pq.read_table(COMPLEXES_FILE, columns=["rgi_id"])["rgi_id"].to_pylist()
    numbers: dict[str, list[int]] = {}
    for rgi_id in ids:
        *_, region, number = rgi_id.split("-")
        numbers.setdefault(region, []).append(int(number))
    assert len(numbers) == 19
    for region, found in numbers.items():
        assert sorted(found) == list(range(1, len(found) + 1)), region
