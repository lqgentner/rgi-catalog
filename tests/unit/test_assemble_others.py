"""Tests for the complexes, centerlines, intersects and regions tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from rgi_catalog import assemble
from rgi_catalog.assemble import glaciers, load_glacier_sources
from rgi_catalog.paths import CACHE

if TYPE_CHECKING:
    from rgi_catalog.fixes import FixReport
    from tests.unit.conftest import FakeRGI

RELEASE_REGIONS = CACHE / "RGI2000-v7.0-regions.zip"


def _fix(report: FixReport, fix: str, column: str) -> int:
    return sum(f.count for f in report if f.fix == fix and f.column == column)


def test_complexes_glacier_ids_mirror_links(fake_rgi: FakeRGI) -> None:
    glacier_table, _ = glaciers(
        load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links),
    )
    complexes, _ = assemble.complexes(fake_rgi.c_zip)
    owners: dict[str, list[str]] = {}
    for complex_id, members in zip(complexes["rgi_id"], complexes["glacier_ids"], strict=True):
        assert list(members) == sorted(members)
        for glacier_id in members:
            owners.setdefault(glacier_id, []).append(complex_id)
    assert all(len(v) == 1 for v in owners.values())
    linked = glacier_table.dropna(subset=["complex_id"])
    assert dict(zip(linked["rgi_id"], linked["complex_id"], strict=True)) == {
        g: c[0] for g, c in owners.items()
    }


def test_complexes_columns_and_types(fake_rgi: FakeRGI) -> None:
    complexes, report = assemble.complexes(fake_rgi.c_zip)
    assert list(complexes.columns) == [*assemble.C_UPSTREAM_COLUMNS, "glacier_ids", "geometry"]
    assert str(complexes["utm_zone"].dtype) == "uint8"
    assert complexes.geometry.is_valid.all()
    assert _fix(report, "polygon-validity", "geometry") == 1
    assert {f.product for f in report} == {"complexes"}


def test_centerlines_one_main_per_glacier(fake_rgi: FakeRGI) -> None:
    lines, _ = assemble.centerlines(fake_rgi.l_zip)
    assert list(lines.columns) == [*assemble.L_UPSTREAM_COLUMNS, "geometry"]
    assert lines["is_main"].dtype == bool
    assert (lines.groupby("rgi_g_id")["is_main"].sum() == 1).all()
    assert str(lines["segment_id"].dtype) == "uint8"
    assert str(lines["outflow_id"].dtype) == "int8"
    assert str(lines["length_m"].dtype) == "uint32"
    assert set(lines.geom_type) == {"LineString"}


def test_intersects_keep_float_length_and_drop_z(fake_rgi: FakeRGI) -> None:
    lines, report = assemble.intersects(fake_rgi.i_zip)
    assert list(lines.columns) == [*assemble.I_UPSTREAM_COLUMNS, "geometry"]
    assert lines["length_m"].dtype == "float64"
    assert lines["length_m"].iloc[0] == 123.456789
    assert not shapely.has_z(lines.geometry.to_numpy()).any()
    assert _fix(report, "drop-z", "geometry") == 1


def test_regions_levels_on_fixture(fake_rgi: FakeRGI) -> None:
    regions, report = assemble.regions(fake_rgi.regions_zip)
    assert list(regions.columns) == assemble.REGION_COLUMNS
    assert str(regions["level"].dtype) == "uint8"
    level1 = regions[regions["level"] == 1]
    # Region 10 is two polygons upstream, split at the antimeridian. It is
    # one row here, so a region code names one row.
    assert len(level1) == 3
    assert level1["o1region"].is_unique
    region10 = level1.loc[level1["o1region"] == "10"].geometry.iloc[0]
    assert region10.geom_type == "MultiPolygon"
    assert len(region10.geoms) == 2
    assert level1["o2region"].isna().all()
    level2 = regions[regions["level"] == 2]
    assert len(level2) == 2
    assert level2["o2region"].notna().all()
    assert set(level2["full_name"]) == {"Sør-Norge", "Alps"}
    assert regions.geometry.is_valid.all()
    assert _fix(report, "text-encoding", "full_name") == 1
    assert _fix(report, "polygon-validity", "geometry") == 1
    assert {f.product for f in report} == {"regions"}


def test_regions_refuse_summary_that_differs(fake_rgi: FakeRGI) -> None:
    o1, o2, s1, s2 = assemble.read_regions(fake_rgi.regions_zip)
    s1.loc[0, "full_name"] = "Somewhere else"
    with pytest.raises(assemble.UpstreamMismatchError, match="summary"):
        assemble.region_table(o1, o2, s1, s2)


@pytest.mark.skipif(not RELEASE_REGIONS.exists(), reason="needs the downloaded regions zip")
def test_regions_levels_in_release() -> None:
    regions, _ = assemble.regions(RELEASE_REGIONS)
    counts = regions["level"].value_counts().to_dict()
    assert counts == {1: 20, 2: 90}
    assert regions.loc[regions["level"] == 1, "o1region"].is_unique
    assert regions.loc[regions["level"] == 2, "o2region"].is_unique
    # RGI's two antimeridian splits: region 10 and region 19-15.
    split = regions.loc[regions["long_code"].isin(["10_north_asia", "19-15_ross_ice_shelf_7e"])]
    assert len(split) == 2
    assert all(g.geom_type == "MultiPolygon" and len(g.geoms) == 2 for g in split.geometry)
    assert regions["full_name"].notna().all()
    assert pd.api.types.is_string_dtype(regions["long_code"])


def test_join_split_regions_refuses_pieces_that_differ() -> None:
    pieces = gpd.GeoDataFrame(
        {
            "level": pd.Series([1, 1], dtype="uint8"),
            "o1region": ["10", "10"],
            "o2region": [None, None],
            "full_name": ["North Asia", "Northern Asia"],
            "long_code": ["10_north_asia", "10_north_asia"],
        },
        geometry=[shapely.box(170, 60, 180, 70), shapely.box(-180, 60, -170, 70)],
        crs="EPSG:4326",
    )
    with pytest.raises(assemble.UpstreamMismatchError, match="10_north_asia"):
        assemble.join_split_regions(pieces)
