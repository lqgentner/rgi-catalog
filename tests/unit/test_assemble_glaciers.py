"""Tests for the glaciers table."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from rgi_catalog.assemble import (
    GLACIER_COLUMNS,
    SUBMISSION_COLUMNS,
    expand_hypsometry,
    glaciers,
    hypsometry_lists,
    load_glacier_sources,
)
from rgi_catalog.upstream import UpstreamMismatchError, read_attributes, read_hypsometry

if TYPE_CHECKING:
    from tests.unit.conftest import FakeRGI

UNLINKED = "RGI2000-v7.0-G-11-00002"


def test_hypsometry_round_trip_exact(fake_rgi: FakeRGI) -> None:
    hyps = read_hypsometry(fake_rgi.g_zip)
    bands = [int(c) for c in hyps.columns[2:]]
    lists = hypsometry_lists(hyps).set_index("rgi_id")
    for _, row in hyps.iterrows():
        got = lists.loc[row["rgi_id"]]
        assert expand_hypsometry(got["hypso_z0_m"], list(got["hypso_permille"]), bands) == [
            int(v) for v in row.iloc[2:]
        ]


def test_hypsometry_lists_trims_and_types(fake_rgi: FakeRGI) -> None:
    lists = hypsometry_lists(read_hypsometry(fake_rgi.g_zip)).set_index("rgi_id")
    row = lists.loc["RGI2000-v7.0-G-11-00001"]
    assert row["hypso_z0_m"] == 2225
    assert list(row["hypso_permille"]) == [423, 464, 113]
    assert str(lists["hypso_z0_m"].dtype) == "Int32"


def test_hypsometry_lists_all_zero_is_null() -> None:
    hyps = pd.DataFrame({"rgi_id": ["a"], "area_km2": [1.0], 2175: [0], 2225: [0]})
    row = hypsometry_lists(hyps).iloc[0]
    assert pd.isna(row["hypso_z0_m"])
    assert row["hypso_permille"] is None or pd.isna(row["hypso_permille"])


def test_glaciers_keeps_every_row_when_side_tables_miss(fake_rgi: FakeRGI) -> None:
    gdf, _ = glaciers(load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links))
    assert len(gdf) == 3
    row = gdf.set_index("rgi_id").loc[UNLINKED]
    assert row["hypso_permille"] is None or pd.isna(row["hypso_permille"])
    assert pd.isna(row["hypso_z0_m"])
    assert pd.isna(row["complex_id"])
    assert list(row["rgi6_links"]) == []
    for column in SUBMISSION_COLUMNS.values():
        assert pd.isna(row[column]), column


def test_glaciers_folds_side_tables(fake_rgi: FakeRGI) -> None:
    gdf, _ = glaciers(load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links))
    row = gdf.set_index("rgi_id").loc["RGI2000-v7.0-G-11-00001"]
    assert row["complex_id"] == "RGI2000-v7.0-C-11-00001"
    assert [link["rgi6_id"] for link in row["rgi6_links"]] == ["RGI60-11.00897", "RGI60-11.00898"]
    assert row["rgi6_links"][0]["overlap_area_km2"] == 0.5
    assert row["subm_n_outlines"] == 4034
    assert row["subm_analysts"] == "Izagirre, Eñaut"
    assert row["display_name"] == "Hintereisferner"


def test_glaciers_applies_name_overrides(fake_rgi: FakeRGI) -> None:
    gdf, _ = glaciers(
        load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links),
        overrides={"Hintereisferner": "Hintereis Ferner"},
    )
    row = gdf.set_index("rgi_id").loc["RGI2000-v7.0-G-11-00001"]
    assert row["glac_name"] == "Hintereisferner"
    assert row["display_name"] == "Hintereis Ferner"


def test_glaciers_rejects_an_override_that_matches_no_glacier(fake_rgi: FakeRGI) -> None:
    with pytest.raises(UpstreamMismatchError, match="Nowhere Glacier"):
        glaciers(
            load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links),
            overrides={"Nowhere Glacier": None},
        )


def test_glaciers_repairs_names_and_reports(fake_rgi: FakeRGI) -> None:
    gdf, report = glaciers(
        load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links),
    )
    row = gdf.set_index("rgi_id").loc["RGI2000-v7.0-G-08-00001"]
    assert row["glac_name"] == "Bessedørbreen"
    assert row["display_name"] == "Bessedørbreen"
    fixes = {(c.fix, c.column): c for c in report}
    assert fixes["text-encoding", "glac_name"].ids == ["RGI2000-v7.0-G-08-00001"]
    assert fixes["text-encoding", "subm_analysts"].count == 2
    assert fixes["drop-z", "geometry"].count == 1
    assert fixes["polygon-validity", "geometry"].count == 0
    assert not gdf.has_z.any()


def test_glaciers_floats_unchanged(fake_rgi: FakeRGI) -> None:
    gdf, _ = glaciers(load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links))
    csv = read_attributes(fake_rgi.g_zip, "G").set_index("rgi_id")
    out = gdf.set_index("rgi_id").loc[csv.index]
    floats = csv.select_dtypes("float64").columns
    assert len(floats) > 0
    for column in floats:
        assert out[column].dtype == np.float64
        assert np.array_equal(out[column].to_numpy(), csv[column].to_numpy()), column


def test_glaciers_types_upstream_columns(fake_rgi: FakeRGI) -> None:
    gdf, _ = glaciers(load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links))
    assert str(gdf["src_date"].dtype) == "datetime64[us]"
    assert gdf["is_rgi6"].dtype == bool
    assert str(gdf["utm_zone"].dtype) == "uint8"
    assert list(gdf["o1region"]) == ["08", "11", "11"]


def test_glaciers_complex_id_unique(fake_rgi: FakeRGI) -> None:
    src = load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links)
    src.ctog["RGI2000-v7.0-C-11-00099"] = ["RGI2000-v7.0-G-11-00001"]
    with pytest.raises(UpstreamMismatchError, match=re.escape("RGI2000-v7.0-G-11-00001")):
        glaciers(src)


def test_glaciers_column_order(fake_rgi: FakeRGI) -> None:
    gdf, _ = glaciers(load_glacier_sources(fake_rgi.g_zip, fake_rgi.c_zip, fake_rgi.rgi6_links))
    upstream = list(read_attributes(fake_rgi.g_zip, "G").columns)
    assert list(gdf.columns) == [
        *upstream,
        "display_name",
        "complex_id",
        "hypso_z0_m",
        "hypso_permille",
        "rgi6_links",
        "subm_n_outlines",
        "subm_anlys_time",
        "subm_release_dt",
        "subm_proc_desc",
        "subm_chief_affl",
        "subm_submitters",
        "subm_analysts",
        "subm_rc_id",
        "geometry",
    ]
    assert list(gdf.columns) == GLACIER_COLUMNS
