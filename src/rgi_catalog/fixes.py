"""Fixes of documented upstream errors (design §5.3).

Each fix applies wherever its error recurs, and reports what it changed. A
kind of error that no fix covers raises :class:`NewErrorKindError` instead
of being repaired on the build's own authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

# C1 control characters are never in a real name. They are left by bytes
# decoded with the wrong code page.
_C1_CONTROLS = re.compile("[\x80-\x9f]")
# Identifier columns are never repaired: rgi_id, rgi_g_id_1, glims_id, …
_ID_COLUMN = re.compile(r"(^|_)id($|_)")
# The column that names a row in a fix report, by preference.
_ROW_KEYS = ("rgi_id", "long_code")


class NewErrorKindError(Exception):
    """The data holds an error of a kind that no documented fix covers."""


@dataclass
class FixCounts:
    """What one fix changed in one column of one product."""

    fix: str
    product: str
    column: str | None
    count: int
    ids: list[str] = field(default_factory=list)


type FixReport = list[FixCounts]


def repair_text(value: str) -> str:
    r"""Undo the two encoding errors found in RGI 7.0 text.

    Some GLIMS submissions stored UTF-8 that was read as Latin-1
    (``"AbbÃ© Glacier"`` for ``"Abbé Glacier"``), and one stored DOS code
    page 437 (``"Mont V\x82lan"`` for ``"Mont Vélan"``). Correct text passes
    through unchanged.

    Parameters
    ----------
    value
        The text as published.

    Returns
    -------
    str
        The repaired text.
    """
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    if _C1_CONTROLS.search(value):
        try:
            return value.encode("latin-1").decode("cp437")
        except UnicodeError:
            return value
    return value


def _repair_cell(value: object) -> object:
    return repair_text(value) if isinstance(value, str) else value


def _with_geometry(gdf: gpd.GeoDataFrame, geoms: np.ndarray) -> gpd.GeoDataFrame:
    """Return a copy of ``gdf`` with its geometry column replaced, in place in the column order."""
    name = gdf.geometry.name
    return gdf.set_geometry(gpd.GeoSeries(geoms, index=gdf.index, crs=gdf.crs, name=name))


def _row_ids(df: pd.DataFrame) -> pd.Series:
    for key in _ROW_KEYS:
        if key in df.columns:
            return df[key].astype(str)
    return pd.Series(df.index.astype(str), index=df.index)


def repair_text_columns(df: pd.DataFrame, product: str) -> tuple[pd.DataFrame, FixReport]:
    """Apply :func:`repair_text` to every text column except identifiers.

    Parameters
    ----------
    df
        The table.
    product
        The product name, for the report.

    Returns
    -------
    tuple[pd.DataFrame, FixReport]
        The repaired copy, and one entry per column that changed.
    """
    out = df.copy()
    report: FixReport = []
    ids = _row_ids(df)
    for column in df.columns:
        if _ID_COLUMN.search(str(column)) or column == "geometry":
            continue
        values = df[column]
        if not (pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values)):
            continue
        texts = values.map(_repair_cell)
        changed = (texts != values) & values.notna()
        if changed.any():
            out[column] = texts
            report.append(
                FixCounts(
                    fix="text-encoding",
                    product=product,
                    column=str(column),
                    count=int(changed.sum()),
                    ids=sorted(ids[changed].tolist()),
                ),
            )
    return out, report


def drop_z(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop the Z coordinate, which RGI 7.0 fills with zeros (rgi_issue_tracker#43).

    Parameters
    ----------
    gdf
        The table.

    Returns
    -------
    gpd.GeoDataFrame
        A copy with 2D geometries.

    Raises
    ------
    NewErrorKindError
        If any Z value is not 0.
    """
    geoms = gdf.geometry.to_numpy()
    z = shapely.get_coordinates(geoms, include_z=True)[:, 2]
    z = z[~np.isnan(z)]
    if (z != 0).any():
        msg = f"{int((z != 0).sum())} coordinate(s) have a Z value other than 0"
        raise NewErrorKindError(msg)
    return _with_geometry(gdf, shapely.force_2d(geoms))


def make_polygons_valid(
    gdf: gpd.GeoDataFrame,
    product: str,
) -> tuple[gpd.GeoDataFrame, FixCounts]:
    """Make invalid polygons valid while keeping each one a single polygon (rgi_issue_tracker#48).

    Only invalid rows change. Collapsed parts (zero-width spikes) are dropped.

    Parameters
    ----------
    gdf
        The table.
    product
        The product name, for the report.

    Returns
    -------
    tuple[gpd.GeoDataFrame, FixCounts]
        The repaired copy, and the rows that changed.

    Raises
    ------
    NewErrorKindError
        If a repaired geometry is not one valid ``Polygon``.
    """
    geoms = gdf.geometry.to_numpy().copy()
    invalid = ~shapely.is_valid(geoms)
    ids = _row_ids(gdf).to_numpy()
    for i in np.flatnonzero(invalid):
        fixed = shapely.make_valid(geoms[i], method="structure", keep_collapsed=False)
        if fixed.geom_type != "Polygon" or not fixed.is_valid:
            msg = f"{ids[i]}: repair gives a {fixed.geom_type}, not one Polygon"
            raise NewErrorKindError(msg)
        geoms[i] = fixed
    out = _with_geometry(gdf, geoms)
    counts = FixCounts(
        fix="polygon-validity",
        product=product,
        column="geometry",
        count=int(invalid.sum()),
        ids=sorted(str(v) for v in ids[invalid]),
    )
    return out, counts
