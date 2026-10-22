"""Tests for the GeoParquet writer."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import Polygon

from rgi_catalog import geoparquet
from rgi_catalog.geoparquet import (
    GEOPARQUET_VERSION,
    KV_KEYS,
    GeoParquetWriteError,
    write_geoparquet,
)

if TYPE_CHECKING:
    from pathlib import Path

N = 5000
ROW_GROUP = 2048
LINK = pa.struct([("rgi6_id", pa.string()), ("overlap_area_km2", pa.float64())])


def _frame() -> gpd.GeoDataFrame:
    rng = np.random.default_rng(0)
    lon = rng.uniform(-170, 170, N)
    lat = rng.uniform(-80, 80, N)
    geoms = [
        Polygon([(x, y), (x + 0.01, y), (x + 0.01, y + 0.01), (x, y + 0.01)])
        for x, y in zip(lon, lat, strict=True)
    ]
    permille = pa.array(
        [None if i % 7 == 0 else [i % 1000, 1000 - i % 1000] for i in range(N)],
        type=pa.list_(pa.int16()),
    )
    links = pa.array(
        [
            [{"rgi6_id": f"RGI60-11.{i:05d}", "overlap_area_km2": i / 3}] * (i % 3)
            for i in range(N)
        ],
        type=pa.list_(LINK),
    )
    return gpd.GeoDataFrame(
        {
            "rgi_id": [f"RGI2000-v7.0-G-11-{i:05d}" for i in range(N)],
            "o1region": ["11"] * N,
            "utm_zone": pd.Series(rng.integers(1, 60, N), dtype="uint8"),
            "area_km2": rng.uniform(0.01, 100, N),
            "is_rgi6": rng.integers(0, 2, N).astype(bool),
            "src_date": pd.Series(pd.Timestamp("2003-08-13"), index=range(N)).astype(
                "datetime64[us]",
            ),
            "glac_name": [None if i % 2 else f"Glacier {i}" for i in range(N)],
            "hypso_z0_m": pd.array(
                [None if i % 7 == 0 else 2000 for i in range(N)], dtype="Int32"
            ),
            "hypso_permille": pd.Series(permille, dtype=pd.ArrowDtype(permille.type)),
            "rgi6_links": pd.Series(links, dtype=pd.ArrowDtype(links.type)),
        },
        geometry=geoms,
        crs="EPSG:4326",
    )


KV = {
    "rgi:version": "7.0",
    "rgi:mirror_revision": "7.0-r1",
    "rgi:sources": json.dumps({"RGI2000-v7.0-G-global.zip": "abc"}),
    "rgi:citation": "RGI 7.0 Consortium, 2023.",
    "rgi:catalog": "https://data.source.coop/lqgentner/rgi/catalog.json",
}


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("gpq") / "out.parquet"
    write_geoparquet(_frame(), out, kv=KV, row_group_size=ROW_GROUP)
    return out


def test_write_geoparquet_format(written: Path) -> None:
    pf = pq.ParquetFile(written)
    meta = pf.metadata
    kv = {k.decode(): v.decode() for k, v in (pf.schema_arrow.metadata or {}).items()}
    geo = json.loads(kv["geo"])
    assert geo["version"].startswith(GEOPARQUET_VERSION)
    assert "bbox" in pf.schema_arrow.names
    assert meta.num_rows == N
    for rg in range(meta.num_row_groups):
        assert meta.row_group(rg).num_rows <= ROW_GROUP
        for col in range(meta.num_columns):
            assert meta.row_group(rg).column(col).compression == "ZSTD"
    footer = {k.decode(): v.decode() for k, v in (meta.metadata or {}).items()}
    for key in KV_KEYS:
        assert footer[key] == KV[key]
    assert not written.with_name(written.name + ".tmp").exists()


def _plain_value(value: object) -> object:
    if isinstance(value, np.ndarray):
        return [_plain_value(v) for v in value.tolist()]
    if isinstance(value, list):
        return [_plain_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain_value(v) for k, v in value.items()}
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _plain(series: pd.Series) -> list[object]:
    return [_plain_value(v) for v in series.tolist()]


def test_write_geoparquet_round_trip(written: Path) -> None:
    want = _frame().sort_values("rgi_id").reset_index(drop=True)
    got = gpd.read_parquet(written).sort_values("rgi_id").reset_index(drop=True)
    assert [c for c in got.columns if c != "bbox"] == list(want.columns)
    table = pq.read_table(written)
    assert table.schema.field("utm_zone").type == pa.uint8()
    assert table.schema.field("hypso_z0_m").type == pa.int32()
    assert table.schema.field("src_date").type == pa.timestamp("us")
    for column in want.columns:
        if column == "geometry":
            continue
        assert _plain(got[column]) == _plain(want[column]), column
    assert shapely.equals_exact(got.geometry.to_numpy(), want.geometry.to_numpy(), 0).all()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_write_geoparquet_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.parquet"
    second = tmp_path / "b.parquet"
    write_geoparquet(_frame(), first, kv=KV, row_group_size=ROW_GROUP)
    write_geoparquet(_frame(), second, kv=KV, row_group_size=ROW_GROUP)
    assert _sha256(first) == _sha256(second)


def test_write_geoparquet_keeps_invalid_geometry_exactly(tmp_path: Path) -> None:
    # The build repairs and reports geometries itself, so the writer must not.
    frame = _frame().iloc[:10].copy()
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    frame.loc[frame.index[0], "geometry"] = bowtie
    out = tmp_path / "invalid.parquet"
    write_geoparquet(frame, out, kv=KV, row_group_size=ROW_GROUP)
    got = gpd.read_parquet(out).set_index("rgi_id").loc[frame["rgi_id"].iloc[0], "geometry"]
    assert shapely.equals_exact(got, bowtie, 0)


def test_write_geoparquet_refuses_row_groups_over_the_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(geoparquet, "MAX_ROW_GROUP_ROWS", 1000)
    with pytest.raises(GeoParquetWriteError, match="1000"):
        write_geoparquet(_frame(), tmp_path / "big.parquet", kv=KV, row_group_size=ROW_GROUP)
    assert not (tmp_path / "big.parquet").exists()
