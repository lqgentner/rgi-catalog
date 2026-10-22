"""Tests for the upstream readers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from rgi_catalog import upstream as upstream_module
from rgi_catalog.upstream import (
    UpstreamMismatchError,
    join_attributes,
    read_attribute_metadata,
    read_attributes,
    read_ctog_links,
    read_geometries,
    read_hypsometry,
    read_rgi6_links,
    read_shapefiles,
    read_submission_info,
)

if TYPE_CHECKING:
    import pandas as pd

    from tests.unit.conftest import FakeRGI


def test_read_geometries_concatenates_regions(fake_rgi: FakeRGI) -> None:
    geoms = read_geometries(fake_rgi.g_zip, "G")
    assert list(geoms.columns) == ["rgi_id", "geometry"]
    assert len(geoms) == 3
    assert geoms["rgi_id"].is_unique
    assert geoms.crs is not None
    assert geoms.crs.to_epsg() == 4326


def test_reader_skips_checkpoints_and_readme(fake_rgi: FakeRGI) -> None:
    attrs = read_attributes(fake_rgi.g_zip, "G")
    assert len(attrs) == 3
    assert "junk" not in attrs.columns


def test_read_attributes_keeps_string_codes(fake_rgi: FakeRGI) -> None:
    attrs = read_attributes(fake_rgi.g_zip, "G")
    assert sorted(attrs["o1region"]) == ["08", "11", "11"]
    assert all(isinstance(v, str) for v in attrs["rgi_id"])
    assert attrs["glac_name"].isna().sum() == 1


def test_read_attribute_metadata(fake_rgi: FakeRGI) -> None:
    meta = read_attribute_metadata(fake_rgi.g_zip, "G")
    assert list(meta)[:3] == ["rgi_id", "o1region", "o2region"]
    assert meta["area_km2"]["datatype"] == "float"


def _frames(fake_rgi: FakeRGI) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    shp = read_shapefiles(fake_rgi.g_zip, "G")
    attrs = read_attributes(fake_rgi.g_zip, "G")
    return shp[["rgi_id", "geometry"]], attrs, shp.drop(columns="geometry")


def test_join_attributes_detects_id_mismatch(fake_rgi: FakeRGI) -> None:
    geoms, attrs, shp_attrs = _frames(fake_rgi)
    with pytest.raises(UpstreamMismatchError, match="rgi_id"):
        join_attributes(geoms, attrs.iloc[1:], shp_attrs)


def test_join_attributes_detects_float_disagreement(fake_rgi: FakeRGI) -> None:
    geoms, attrs, shp_attrs = _frames(fake_rgi)
    attrs.loc[attrs.index[0], "cenlon"] += 1e-9
    with pytest.raises(UpstreamMismatchError, match="cenlon"):
        join_attributes(geoms, attrs, shp_attrs)


def test_join_attributes_accepts_dbf_rounding(fake_rgi: FakeRGI) -> None:
    geoms, attrs, shp_attrs = _frames(fake_rgi)
    attrs.loc[attrs.index[0], "cenlon"] += 1e-15
    joined = join_attributes(geoms, attrs, shp_attrs)
    assert len(joined) == 3
    assert list(joined.columns) == [*attrs.columns, "geometry"]
    # The CSV value wins: it carries the full decimal text.
    first = joined.set_index("rgi_id").loc[attrs["rgi_id"].iloc[0], "cenlon"]
    assert first == attrs["cenlon"].iloc[0]


def test_join_attributes_detects_integer_disagreement(fake_rgi: FakeRGI) -> None:
    geoms, attrs, shp_attrs = _frames(fake_rgi)
    attrs.loc[attrs.index[0], "lmax_m"] += 1
    with pytest.raises(UpstreamMismatchError, match="lmax_m"):
        join_attributes(geoms, attrs, shp_attrs)


def test_read_ctog_links(fake_rgi: FakeRGI) -> None:
    assert read_ctog_links(fake_rgi.c_zip) == {
        "RGI2000-v7.0-C-08-00001": ["RGI2000-v7.0-G-08-00001"],
        "RGI2000-v7.0-C-11-00001": ["RGI2000-v7.0-G-11-00001"],
    }


def test_read_submission_info_keys_on_region_and_submission(fake_rgi: FakeRGI) -> None:
    # Submission 731 spans regions 08 and 11. Its counts are per region, so
    # each region keeps its own row.
    subm = read_submission_info(fake_rgi.g_zip)
    assert list(zip(subm["o1region"], subm["subm_id"], strict=True)) == [("08", 731), ("11", 731)]
    assert subm["analysts"].iloc[0] == "Izagirre, E\u00c3\u00b1aut"


def test_read_submission_info_refuses_differing_text_across_regions(
    fake_rgi: FakeRGI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = upstream_module._concat_csv

    def changed(*args: object, **kwargs: object) -> pd.DataFrame:
        frame = real(*args, **kwargs)  # type: ignore[arg-type]
        frame.loc[frame.index[-1], "proc_desc"] = "something else"
        return frame

    monkeypatch.setattr(upstream_module, "_concat_csv", changed)
    with pytest.raises(UpstreamMismatchError, match="731"):
        read_submission_info(fake_rgi.g_zip)


def test_read_hypsometry_bands_as_int(fake_rgi: FakeRGI) -> None:
    hyps = read_hypsometry(fake_rgi.g_zip)
    assert list(hyps.columns[:2]) == ["rgi_id", "area_km2"]
    assert list(hyps.columns[2:]) == [2175, 2225, 2275, 2325, 2375]
    row = hyps.set_index("rgi_id").loc["RGI2000-v7.0-G-08-00001"]
    assert list(row.iloc[1:]) == [0, 500, 500, 0, 0]


def test_read_rgi6_links(fake_rgi: FakeRGI) -> None:
    links = read_rgi6_links(fake_rgi.rgi6_links)
    assert len(links) == 3
    assert links.columns[0] == "rgi7_id"
    assert links["rgi7_reg"].iloc[0] == "08"
