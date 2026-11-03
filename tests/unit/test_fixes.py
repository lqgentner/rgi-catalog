"""Tests for the fixes of documented upstream errors."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
import shapely
from shapely.geometry import LineString, Polygon

from rgi_catalog.fixes import (
    NewErrorKindError,
    drop_z,
    make_polygons_valid,
    repair_text,
    repair_text_columns,
)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("AbbÃ© Glacier", "Abbé Glacier"),
        ("BessedÃ¸rbreen", "Bessedørbreen"),
    ],
)
def test_repair_text_utf8_mojibake(raw: str, want: str) -> None:
    assert repair_text(raw) == want


def test_repair_text_cp437() -> None:
    assert repair_text("Mont V\x82lan-W") == "Mont Vélan-W"


@pytest.mark.parametrize("text", ["Eñaut", "Hintereisferner", "Ледник", "S/N", ""])
def test_repair_text_leaves_correct_text(text: str) -> None:
    assert repair_text(text) == text


def test_repair_text_columns_covers_non_name_columns() -> None:
    df = pd.DataFrame(
        {
            "rgi_id": ["RGI2000-v7.0-G-11-00001", "RGI2000-v7.0-G-11-00002"],
            "subm_analysts": ["Izagirre, EÃ±aut", "Paul, Frank"],
            "full_name": ["CÃ´te", None],
            "area_km2": [1.0, 2.0],
        },
    )
    fixed, counts = repair_text_columns(df, "glaciers")
    assert list(fixed["subm_analysts"]) == ["Izagirre, Eñaut", "Paul, Frank"]
    assert fixed["full_name"].iloc[0] == "Côte"
    assert pd.isna(fixed["full_name"].iloc[1])
    assert list(fixed["rgi_id"]) == list(df["rgi_id"])
    by_column = {c.column: c for c in counts}
    assert set(by_column) == {"subm_analysts", "full_name"}
    assert by_column["subm_analysts"].count == 1
    assert by_column["subm_analysts"].ids == ["RGI2000-v7.0-G-11-00001"]
    assert by_column["full_name"].count == 1
    assert all(c.fix == "text-encoding" and c.product == "glaciers" for c in counts)


def test_repair_text_columns_skips_id_columns() -> None:
    df = pd.DataFrame({"rgi_id": ["AÃ©"], "rgi_g_id": ["AÃ©"], "glims_id": ["AÃ©"]})
    fixed, counts = repair_text_columns(df, "centerlines")
    assert fixed.equals(df)
    assert counts == []


def _gdf(geoms: list[object]) -> gpd.GeoDataFrame:
    ids = [f"RGI2000-v7.0-G-11-0000{i}" for i in range(1, len(geoms) + 1)]
    return gpd.GeoDataFrame({"rgi_id": ids}, geometry=geoms, crs="EPSG:4326")


def test_drop_z_removes_zero_z() -> None:
    gdf = _gdf(
        [
            Polygon([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 0, 0)]),
            LineString([(0, 0, 0), (1, 1, 0)]),
        ],
    )
    out = drop_z(gdf)
    assert not out.has_z.any()
    assert shapely.equals_exact(out.geometry.iloc[0], Polygon([(0, 0), (1, 0), (1, 1)]), 0)


def test_drop_z_refuses_nonzero_z() -> None:
    gdf = _gdf([LineString([(0, 0, 0), (1, 1, 5)])])
    with pytest.raises(NewErrorKindError):
        drop_z(gdf)


def test_make_polygons_valid_fixes_spike() -> None:
    valid = Polygon([(10, 10), (11, 10), (11, 11), (10, 11)])
    # A zero-width spike from (1, 1) out to (2, 1) and back.
    spike = Polygon([(0, 0), (1, 0), (1, 1), (2, 1), (1, 1), (0, 1)])
    assert not spike.is_valid
    gdf = _gdf([valid, spike])
    out, counts = make_polygons_valid(gdf, "glaciers")
    fixed = out.geometry.iloc[1]
    assert fixed.geom_type == "Polygon"
    assert fixed.is_valid
    assert fixed.area == pytest.approx(1.0)
    assert out.geometry.iloc[0] is gdf.geometry.iloc[0]
    assert shapely.equals_exact(out.geometry.iloc[0], valid, 0)
    assert counts.fix == "polygon-validity"
    assert counts.count == 1
    assert counts.ids == ["RGI2000-v7.0-G-11-00002"]


def test_make_polygons_valid_refuses_split() -> None:
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    with pytest.raises(NewErrorKindError):
        make_polygons_valid(_gdf([bowtie]), "glaciers")
