"""Readers for the RGI 7.0 release: nested per-region zips and their side files.

Each global zip holds one zip per first-order region. The readers iterate
those inner zips and skip the ``.ipynb_checkpoints/`` folders and the
``README.md`` files that the release ships by mistake (issues #42 and #49).
"""

from __future__ import annotations

from contextlib import contextmanager
import io
import json
from pathlib import Path, PurePosixPath
import re
from typing import TYPE_CHECKING, Any, Literal, cast
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterator

type Product = Literal["G", "C", "I", "L"]

FLOAT_TOLERANCE = 1e-12
WGS84 = 4326


class UpstreamMismatchError(Exception):
    """Two upstream sources that must agree do not."""


def _is_junk(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return ".ipynb_checkpoints" in parts or PurePosixPath(name).name == "README.md"


@contextmanager
def _region_zips(global_zip: Path) -> Iterator[list[tuple[str, zipfile.ZipFile]]]:
    """Open every inner region zip of a global zip, sorted by name."""
    with zipfile.ZipFile(global_zip) as outer:
        names = sorted(n for n in outer.namelist() if n.endswith(".zip") and not _is_junk(n))
        inner = [(n, zipfile.ZipFile(io.BytesIO(outer.read(n)))) for n in names]
        try:
            yield inner
        finally:
            for _, zf in inner:
                zf.close()


def _read_vector(path: str) -> gpd.GeoDataFrame:
    return cast("gpd.GeoDataFrame", pyogrio.read_dataframe(path))


def _members(zf: zipfile.ZipFile, suffix: str) -> list[str]:
    return sorted(n for n in zf.namelist() if n.endswith(suffix) and not _is_junk(n))


def _one_member(zf: zipfile.ZipFile, suffix: str) -> str:
    found = _members(zf, suffix)
    if len(found) != 1:
        msg = f"expected one member ending in {suffix!r}, found {found}"
        raise UpstreamMismatchError(msg)
    return found[0]


def _read_csv(data: bytes, str_columns: list[str]) -> pd.DataFrame:
    """Read an RGI CSV. Only the empty string is missing, so a name like "NA" stays text."""
    frame = pd.read_csv(
        io.BytesIO(data),
        dtype=cast("dict[Hashable, Any]", dict.fromkeys(str_columns, str)),
        keep_default_na=False,
        na_values=[""],
    )
    unnamed = [c for c in frame.columns if c == "" or str(c).startswith("Unnamed:")]
    return frame.drop(columns=unnamed)


def _str_columns(metadata: dict[str, dict[str, str]]) -> list[str]:
    return [name for name, meta in metadata.items() if meta.get("datatype") == "str"]


def read_shapefiles(global_zip: Path, product: Product) -> gpd.GeoDataFrame:
    """Read every region's shapefile, with its ``.dbf`` attributes.

    Parameters
    ----------
    global_zip
        The global zip of the product.
    product
        The product letter.

    Returns
    -------
    gpd.GeoDataFrame
        All regions concatenated in region order, in EPSG:4326.
    """
    del product
    frames: list[gpd.GeoDataFrame] = []
    with _region_zips(global_zip) as regions:
        for inner_name, zf in regions:
            shp = _one_member(zf, ".shp")
            path = f"/vsizip//vsizip/{global_zip.resolve()}/{inner_name}/{shp}"
            frames.append(_read_vector(path))
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    if gdf.crs is None or gdf.crs.to_epsg() != WGS84:
        msg = f"{global_zip.name}: expected EPSG:{WGS84}, found {gdf.crs}"
        raise UpstreamMismatchError(msg)
    return gdf


def read_geometries(global_zip: Path, product: Product) -> gpd.GeoDataFrame:
    """Read every region's outlines.

    Parameters
    ----------
    global_zip
        The global zip of the product.
    product
        The product letter.

    Returns
    -------
    gpd.GeoDataFrame
        Columns ``rgi_id`` and ``geometry``.
    """
    gdf = read_shapefiles(global_zip, product)
    return gpd.GeoDataFrame(gdf[["rgi_id", "geometry"]], crs=gdf.crs)


def read_attribute_metadata(global_zip: Path, product: Product) -> dict[str, dict[str, str]]:
    """Read the ``-attributes_metadata.json`` files, which are the same in every region.

    Parameters
    ----------
    global_zip
        The global zip of the product.
    product
        The product letter.

    Returns
    -------
    dict[str, dict[str, str]]
        Per column: ``long_name``, ``description``, ``datatype``, ``units``,
        ``source``, ``rgi6_name``.

    Raises
    ------
    UpstreamMismatchError
        If two regions disagree.
    """
    del product
    merged: dict[str, dict[str, str]] | None = None
    with _region_zips(global_zip) as regions:
        for inner_name, zf in regions:
            meta = json.loads(zf.read(_one_member(zf, "-attributes_metadata.json")))
            if merged is None:
                merged = meta
            elif meta != merged:
                msg = f"{inner_name}: attributes metadata differs from the first region"
                raise UpstreamMismatchError(msg)
    if merged is None:
        msg = f"{global_zip.name}: no region zips"
        raise UpstreamMismatchError(msg)
    return merged


def _region_code(inner_name: str) -> str:
    """Return the region code of an inner zip: ``"11"`` for ``…-G-11_central_europe.zip``."""
    match = re.search(r"-(\d{2})_[^/]*\.zip$", inner_name)
    if match is None:
        msg = f"no region code in {inner_name!r}"
        raise UpstreamMismatchError(msg)
    return match.group(1)


def _concat_csv(
    global_zip: Path,
    suffix: str,
    str_columns: Callable[[zipfile.ZipFile], list[str]],
    *,
    region_column: str | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    with _region_zips(global_zip) as regions:
        for inner_name, zf in regions:
            for name in _members(zf, suffix):
                frame = _read_csv(zf.read(name), str_columns(zf))
                if region_column is not None:
                    frame.insert(0, region_column, _region_code(inner_name))
                frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def read_attributes(global_zip: Path, product: Product) -> pd.DataFrame:
    """Read every region's ``-attributes.csv``.

    String columns (by the metadata ``datatype``) stay text, so codes like
    ``o1region = "01"`` keep their leading zeros. Other columns take pandas'
    parse.

    Parameters
    ----------
    global_zip
        The global zip of the product.
    product
        The product letter.

    Returns
    -------
    pd.DataFrame
        All regions concatenated in region order.
    """
    del product

    def columns(zf: zipfile.ZipFile) -> list[str]:
        return _str_columns(json.loads(zf.read(_one_member(zf, "-attributes_metadata.json"))))

    return _concat_csv(global_zip, "-attributes.csv", columns)


def read_hypsometry(g_zip: Path) -> pd.DataFrame:
    """Read every region's ``-hypsometry.csv``.

    Parameters
    ----------
    g_zip
        The glaciers global zip.

    Returns
    -------
    pd.DataFrame
        ``rgi_id``, ``area_km2``, then one column per 50 m band, named by its
        centre elevation as an ``int`` and sorted. A band that a region's file
        lacks is 0 for that region's glaciers.
    """
    hyps = _concat_csv(g_zip, "-hypsometry.csv", lambda _: ["rgi_id"])
    bands = sorted(int(c) for c in hyps.columns[2:])
    hyps = hyps.rename(columns={c: int(c) for c in hyps.columns[2:]})
    out = hyps[["rgi_id", "area_km2", *bands]].copy()
    out[bands] = out[bands].fillna(0).astype(np.int64)
    return out


def read_submission_info(g_zip: Path) -> pd.DataFrame:
    """Read the submission tables, one row per first-order region and ``subm_id``.

    A submission that spans regions appears in each region's table. Its
    ``n_outlines`` and ``area_km2`` count only the outlines of that region,
    so the rows are kept per region, with the region code in ``o1region``.

    Parameters
    ----------
    g_zip
        The glaciers global zip.

    Returns
    -------
    pd.DataFrame
        ``o1region`` then the upstream columns, sorted by ``o1region`` and
        ``subm_id``.

    Raises
    ------
    UpstreamMismatchError
        If a region lists a submission twice, or if a submission's descriptive
        text differs between regions.
    """
    text = ["anlys_time", "release_dt", "proc_desc", "chief_affl", "submitters", "analysts"]
    subm = _concat_csv(g_zip, "-submission_info.csv", lambda _: text, region_column="o1region")
    key = ["o1region", "subm_id"]
    if subm.duplicated(subset=key).any():
        dups = subm.loc[subm.duplicated(subset=key), key].to_numpy().tolist()
        msg = f"submissions listed twice in one region: {dups}"
        raise UpstreamMismatchError(msg)
    descriptive = ["subm_id", *text, "rc_id"]
    inconsistent = subm.drop_duplicates(subset=descriptive)["subm_id"].duplicated()
    if inconsistent.any():
        ids = sorted(subm.drop_duplicates(subset=descriptive).loc[inconsistent, "subm_id"])
        msg = f"submissions whose text differs between regions: {ids}"
        raise UpstreamMismatchError(msg)
    return subm.sort_values(key).reset_index(drop=True)


def read_ctog_links(c_zip: Path) -> dict[str, list[str]]:
    """Read the complex-to-glacier links of every region.

    Parameters
    ----------
    c_zip
        The complexes global zip.

    Returns
    -------
    dict[str, list[str]]
        Glacier IDs by complex ID.

    Raises
    ------
    UpstreamMismatchError
        If a complex ID appears in two regions.
    """
    links: dict[str, list[str]] = {}
    with _region_zips(c_zip) as regions:
        for _, zf in regions:
            part: dict[str, list[str]] = json.loads(zf.read(_one_member(zf, "-CtoG_links.json")))
            if overlap := links.keys() & part.keys():
                msg = f"complex IDs in two regions: {sorted(overlap)[:5]}"
                raise UpstreamMismatchError(msg)
            links.update(part)
    return links


def read_rgi6_links(csv: Path) -> pd.DataFrame:
    """Read the corrected RGI 7 to RGI 6 links.

    Parameters
    ----------
    csv
        The global links CSV (rgi_issue_tracker#41).

    Returns
    -------
    pd.DataFrame
        One row per link. IDs and region codes stay text.
    """
    return _read_csv(csv.read_bytes(), ["rgi7_id", "rgi6_id", "rgi7_reg", "rgi6_reg"])


def read_regions(
    regions_zip: Path,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the region outlines and their summary tables.

    Parameters
    ----------
    regions_zip
        The regions zip.

    Returns
    -------
    tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]
        First-order outlines, second-order outlines, first-order summary,
        second-order summary.
    """
    text = ["o1region", "o2region", "full_name", "long_code"]
    with zipfile.ZipFile(regions_zip) as zf:
        o1_sum = _read_csv(zf.read(_one_member(zf, "-o1regions-summary.csv")), text)
        o2_sum = _read_csv(zf.read(_one_member(zf, "-o2regions-summary.csv")), text)
        shp1 = _one_member(zf, "-o1regions.shp")
        shp2 = _one_member(zf, "-o2regions.shp")
    base = f"/vsizip/{regions_zip.resolve()}"
    o1 = _read_vector(f"{base}/{shp1}")
    o2 = _read_vector(f"{base}/{shp2}")
    return o1, o2, o1_sum, o2_sum


def join_attributes(
    geoms: pd.DataFrame,
    attrs: pd.DataFrame,
    shp_attrs: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Join the CSV attributes to the outlines, after checking them against the ``.dbf``.

    The CSV carries full decimal text, so its values are kept. The ``.dbf``
    is only the witness: both must hold the same IDs, floats must agree
    within ``1e-12`` (DBF text rounding), and integers exactly.

    Parameters
    ----------
    geoms
        ``rgi_id`` and ``geometry``.
    attrs
        The ``-attributes.csv`` rows.
    shp_attrs
        The ``.dbf`` attributes.

    Returns
    -------
    gpd.GeoDataFrame
        The CSV columns in their order, then ``geometry``, in the order of ``attrs``.

    Raises
    ------
    UpstreamMismatchError
        If the ID sets differ, an ID repeats, or a shared numeric column disagrees.
    """
    ids = attrs["rgi_id"]
    if (
        not ids.is_unique
        or set(ids) != set(geoms["rgi_id"])
        or set(ids)
        != set(
            shp_attrs["rgi_id"],
        )
    ):
        msg = "rgi_id sets differ between the attributes CSV and the shapefile"
        raise UpstreamMismatchError(msg)
    witness = shp_attrs.set_index("rgi_id").reindex(ids)
    for column in attrs.columns.intersection(witness.columns):
        csv_values = attrs[column].to_numpy()
        dbf_values = witness[column].to_numpy()
        if pd.api.types.is_float_dtype(attrs[column]):
            bad = ~np.isclose(csv_values, dbf_values, rtol=0, atol=FLOAT_TOLERANCE, equal_nan=True)
        elif pd.api.types.is_integer_dtype(attrs[column]):
            bad = csv_values != dbf_values
        else:
            continue
        if bad.any():
            first = ids.iloc[int(np.flatnonzero(bad)[0])]
            msg = f"{column}: {int(bad.sum())} value(s) differ between CSV and .dbf, e.g. {first}"
            raise UpstreamMismatchError(msg)
    geometry = geoms.set_index("rgi_id")["geometry"].reindex(ids)
    out = attrs.reset_index(drop=True).copy()
    return gpd.GeoDataFrame(out, geometry=geometry.to_numpy(), crs="EPSG:4326")
