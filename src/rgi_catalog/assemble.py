"""Assemble one table per feature kind (design §5.2).

Side tables are folded into the row they describe. Every join is a left join
from the product's own rows, and the row count is checked after each one, so
a glacier that a side table misses keeps its row with nulls or empty lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa

from rgi_catalog.dtypes import narrow_int, to_timestamp, type_upstream
from rgi_catalog.fixes import FixCounts, drop_z, make_polygons_valid, repair_text_columns
from rgi_catalog.names import display_name
from rgi_catalog.upstream import (
    UpstreamMismatchError,
    join_attributes,
    read_attributes,
    read_ctog_links,
    read_hypsometry,
    read_rgi6_links,
    read_shapefiles,
    read_submission_info,
)

if TYPE_CHECKING:
    from pathlib import Path

    from rgi_catalog.fixes import FixReport

HYPSO_BAND_M = 50

G_UPSTREAM_COLUMNS = [
    "rgi_id",
    "o1region",
    "o2region",
    "glims_id",
    "anlys_id",
    "subm_id",
    "src_date",
    "cenlon",
    "cenlat",
    "utm_zone",
    "area_km2",
    "primeclass",
    "conn_lvl",
    "surge_type",
    "term_type",
    "glac_name",
    "is_rgi6",
    "termlon",
    "termlat",
    "zmin_m",
    "zmax_m",
    "zmed_m",
    "zmean_m",
    "slope_deg",
    "aspect_deg",
    "aspect_sec",
    "dem_source",
    "lmax_m",
]
SUBMISSION_COLUMNS = {
    "n_outlines": "subm_n_outlines",
    "anlys_time": "subm_anlys_time",
    "release_dt": "subm_release_dt",
    "proc_desc": "subm_proc_desc",
    "chief_affl": "subm_chief_affl",
    "submitters": "subm_submitters",
    "analysts": "subm_analysts",
    "rc_id": "subm_rc_id",
}
GLACIER_COLUMNS = [
    *G_UPSTREAM_COLUMNS,
    "display_name",
    "complex_id",
    "hypso_z0_m",
    "hypso_permille",
    "rgi6_links",
    *SUBMISSION_COLUMNS.values(),
    "geometry",
]
RGI6_LINK_FIELDS: dict[str, pa.DataType] = {
    "rgi6_id": pa.string(),
    "rgi7_reg": pa.string(),
    "rgi6_reg": pa.string(),
    "overlap_area_km2": pa.float64(),
    "rgi7_area_fraction": pa.float64(),
    "rgi6_area_fraction": pa.float64(),
    "cluster_id": pa.int32(),
    "n_rgi7": pa.int32(),
    "n_rgi6": pa.int32(),
}


@dataclass
class GlacierSources:
    """The upstream inputs of the glaciers table."""

    outlines: gpd.GeoDataFrame
    hypsometry: pd.DataFrame
    submissions: pd.DataFrame
    ctog: dict[str, list[str]]
    rgi6_links: pd.DataFrame


def load_glacier_sources(g_zip: Path, c_zip: Path, rgi6_csv: Path) -> GlacierSources:
    """Read every input of the glaciers table.

    Parameters
    ----------
    g_zip
        The glaciers global zip.
    c_zip
        The complexes global zip, for the complex-to-glacier links.
    rgi6_csv
        The corrected RGI 6 links.

    Returns
    -------
    GlacierSources
        The inputs, with the attributes CSV joined to the outlines.
    """
    shp = read_shapefiles(g_zip, "G")
    outlines = join_attributes(
        shp[["rgi_id", "geometry"]],
        read_attributes(g_zip, "G"),
        shp.drop(columns="geometry"),
    )
    return GlacierSources(
        outlines=outlines,
        hypsometry=read_hypsometry(g_zip),
        submissions=read_submission_info(g_zip),
        ctog=read_ctog_links(c_zip),
        rgi6_links=read_rgi6_links(rgi6_csv),
    )


def hypsometry_lists(hyps: pd.DataFrame) -> pd.DataFrame:
    """Fold the hypsometry bands into a first-band elevation and a list.

    Parameters
    ----------
    hyps
        ``rgi_id``, ``area_km2``, then one column per band, named by its
        centre elevation and sorted (as :func:`~rgi_catalog.upstream.read_hypsometry`
        returns).

    Returns
    -------
    pd.DataFrame
        ``rgi_id``; ``hypso_z0_m`` (``Int32``), the centre elevation of the
        first non-zero band; ``hypso_permille`` (``list<int16>``), the ‰
        values from that band to the last non-zero band. Both are null for a
        glacier whose bands are all zero.
    """
    bands = np.array([int(c) for c in hyps.columns[2:]], dtype=np.int64)
    matrix = hyps.iloc[:, 2:].to_numpy(dtype=np.int64)
    if matrix.size and (matrix.min() < 0 or matrix.max() > np.iinfo(np.int16).max):
        msg = "hypsometry values outside the int16 range"
        raise UpstreamMismatchError(msg)
    nonzero = matrix != 0
    present = nonzero.any(axis=1)
    first = nonzero.argmax(axis=1)
    last = matrix.shape[1] - 1 - nonzero[:, ::-1].argmax(axis=1)
    column = np.arange(matrix.shape[1])
    keep = (column >= first[:, None]) & (column <= last[:, None]) & present[:, None]
    lengths = keep.sum(axis=1)
    offsets = np.concatenate([[0], np.cumsum(lengths)]).astype(np.int32)
    values = pa.array(matrix[keep].astype(np.int16), type=pa.int16())
    lists = pa.ListArray.from_arrays(pa.array(offsets), values, mask=pa.array(~present))
    z0 = pd.array(np.where(present, bands[first] if bands.size else 0, 0), dtype="Int32")
    z0[~present] = pd.NA
    return pd.DataFrame(
        {
            "rgi_id": hyps["rgi_id"].to_numpy(),
            "hypso_z0_m": z0,
            "hypso_permille": _arrow_series(lists),
        },
    )


def _arrow_series(values: pa.Array) -> pd.Series:
    return pd.Series(values, dtype=pd.ArrowDtype(values.type))


def expand_hypsometry(z0: int | None, permille: list[int] | None, bands: list[int]) -> list[int]:
    """Rebuild the band values of one glacier, the inverse of :func:`hypsometry_lists`.

    Parameters
    ----------
    z0
        ``hypso_z0_m``, or ``None``.
    permille
        ``hypso_permille``, or ``None``.
    bands
        The centre elevations of all bands.

    Returns
    -------
    list[int]
        One value per band.
    """
    out = [0] * len(bands)
    if z0 is None or permille is None or pd.isna(z0):
        return out
    start = bands.index(int(z0))
    out[start : start + len(permille)] = [int(v) for v in permille]
    return out


def _complex_ids(rgi_ids: pd.Series, ctog: dict[str, list[str]]) -> pd.Series:
    pairs = pd.DataFrame(
        [(g, c) for c, members in ctog.items() for g in members],
        columns=["rgi_id", "complex_id"],
    )
    if pairs["rgi_id"].duplicated().any():
        dups = sorted(pairs.loc[pairs["rgi_id"].duplicated(keep=False), "rgi_id"].unique())
        msg = f"glaciers listed under two complexes: {dups[:10]}"
        raise UpstreamMismatchError(msg)
    return rgi_ids.map(pairs.set_index("rgi_id")["complex_id"]).astype("str")


def _rgi6_lists(rgi_ids: pd.Series, links: pd.DataFrame) -> pd.Series:
    position = pd.Series(np.arange(len(rgi_ids)), index=rgi_ids.to_numpy())
    pos = links["rgi7_id"].map(position)
    if pos.isna().any():
        unknown = sorted(links.loc[pos.isna(), "rgi7_id"].unique())
        msg = f"RGI 6 links name unknown glaciers: {unknown[:10]}"
        raise UpstreamMismatchError(msg)
    pos_values = pos.to_numpy(dtype=np.int64)
    order = np.argsort(pos_values, kind="stable")
    ordered = links.iloc[order]
    fields = []
    for name, arrow_type in RGI6_LINK_FIELDS.items():
        values = ordered[name]
        if pa.types.is_int32(arrow_type):
            values = narrow_int(values, "int32")
        fields.append(pa.array(values.to_numpy(), type=arrow_type))
    structs = pa.StructArray.from_arrays(fields, names=list(RGI6_LINK_FIELDS))
    counts = np.bincount(pos_values, minlength=len(rgi_ids))
    offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int32)
    lists = pa.ListArray.from_arrays(pa.array(offsets), structs)
    return _arrow_series(lists)


def _typed_submissions(subm: pd.DataFrame) -> pd.DataFrame:
    out = subm[["o1region", "subm_id", *SUBMISSION_COLUMNS]].rename(columns=SUBMISSION_COLUMNS)
    out["subm_id"] = narrow_int(out["subm_id"], "uint16")
    out["subm_n_outlines"] = narrow_int(out["subm_n_outlines"], "UInt32")
    out["subm_rc_id"] = narrow_int(out["subm_rc_id"], "UInt16")
    out["subm_anlys_time"] = to_timestamp(out["subm_anlys_time"])
    out["subm_release_dt"] = to_timestamp(out["subm_release_dt"])
    return out


def _left_join(left: pd.DataFrame, right: pd.DataFrame, on: list[str]) -> pd.DataFrame:
    if right.duplicated(subset=on).any():
        msg = f"side table repeats a key on {on}"
        raise UpstreamMismatchError(msg)
    out = left.merge(right, on=on, how="left", validate="many_to_one")
    if len(out) != len(left):
        msg = f"join on {on} changed the row count: {len(left)} -> {len(out)}"
        raise UpstreamMismatchError(msg)
    return out


def glaciers(src: GlacierSources) -> tuple[gpd.GeoDataFrame, FixReport]:
    """Assemble the glaciers table and apply the documented fixes.

    Parameters
    ----------
    src
        The upstream inputs.

    Returns
    -------
    tuple[gpd.GeoDataFrame, FixReport]
        One row per glacier, columns in :data:`GLACIER_COLUMNS` order, and
        the fixes applied.
    """
    outlines = src.outlines
    n = len(outlines)
    table = type_upstream(pd.DataFrame(outlines.drop(columns="geometry")))
    table["complex_id"] = _complex_ids(table["rgi_id"], src.ctog)
    table = _left_join(table, hypsometry_lists(src.hypsometry), ["rgi_id"])
    table["rgi6_links"] = _rgi6_lists(table["rgi_id"], src.rgi6_links)
    table = _left_join(table, _typed_submissions(src.submissions), ["o1region", "subm_id"])
    if len(table) != n:
        msg = f"glaciers table has {len(table)} rows, outlines {n}"
        raise UpstreamMismatchError(msg)

    table, report = repair_text_columns(table, "glaciers")
    table["display_name"] = pd.Series(
        [display_name(v if isinstance(v, str) else None) for v in table["glac_name"]],
        dtype="str",
    )
    gdf = gpd.GeoDataFrame(table, geometry=outlines.geometry.to_numpy(), crs=outlines.crs)

    with_z = int(gdf.has_z.sum())
    gdf = drop_z(gdf)
    report.append(FixCounts(fix="drop-z", product="glaciers", column="geometry", count=with_z))
    gdf, validity = make_polygons_valid(gdf, "glaciers")
    report.append(validity)
    return gpd.GeoDataFrame(gdf[GLACIER_COLUMNS], crs=gdf.crs), report
