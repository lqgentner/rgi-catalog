"""Write GeoParquet through gpio (geoparquet-io), as design §5.5 sets out.

geopandas writes a plain intermediate file that carries the key-value
metadata. gpio's Python API then adds the bbox covering column, orders the
rows and writes the published file in one pass: GeoParquet 2.0, zstd level 19
and the chosen row group size. The rows follow the Hilbert curve, or a column
of unique values when the caller names one. gpio carries the
input's non-geo key-value metadata into the output (geoparquet-io #690).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Literal

import geoparquet_io as gpio
import pyarrow.parquet as pq

if TYPE_CHECKING:
    import geopandas as gpd

GEOPARQUET_VERSION: Literal["2.0", "1.1"] = "2.0"
# A target, not a limit: gpio's DuckDB writer makes groups of about 10,300 to
# 12,100 rows on the glaciers table. docs/DESIGN.md has the measurements.
ROW_GROUP_SIZE: int = 10_240
COMPRESSION_LEVEL = 19
# The Portolan cap on rows per row group (PORTO-FMT-009).
MAX_ROW_GROUP_ROWS = 150_000
KV_KEYS = ("rgi:version", "rgi:mirror_revision", "rgi:sources", "rgi:citation", "rgi:catalog")


class GeoParquetWriteError(Exception):
    """A written file breaks a setting it was written with."""


def write_geoparquet(
    gdf: gpd.GeoDataFrame,
    out: Path,
    *,
    kv: dict[str, str],
    row_group_size: int = ROW_GROUP_SIZE,
    order_by: str | None = None,
) -> None:
    """Write a GeoDataFrame as published GeoParquet.

    Geometries are written as given. The build repairs them beforehand and
    reports each repair.

    Parameters
    ----------
    gdf
        The table, in EPSG:4326 with 2D geometries.
    out
        The destination. It is replaced only once the new file is complete.
    kv
        Footer key-value metadata. Must hold every key in :data:`KV_KEYS`.
    row_group_size
        The target rows per row group. gpio rounds a value above 2,048 to a
        multiple of 2,048, and its writer treats the result as a target.
    order_by
        A column of unique values to order the rows by. Each row group then
        holds a disjoint range of the column, so a filter on one value selects
        one row group. ``None`` orders the rows on the Hilbert curve.

    Raises
    ------
    ValueError
        If ``kv`` lacks a key of :data:`KV_KEYS`, or ``order_by`` holds a
        duplicate value.
    GeoParquetWriteError
        If a written row group has more than :data:`MAX_ROW_GROUP_ROWS` rows.
    """
    if missing := [k for k in KV_KEYS if k not in kv]:
        msg = f"kv metadata lacks {missing}"
        raise ValueError(msg)
    if order_by is not None and not gdf[order_by].is_unique:
        msg = f"order_by column {order_by!r} holds duplicate values"
        raise ValueError(msg)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=f".{out.stem}-") as work:
        plain = Path(work) / "plain.parquet"
        gdf.to_parquet(plain, index=False)
        table = pq.read_table(plain)
        extra = {k.encode(): v.encode() for k, v in kv.items()}
        pq.write_table(
            table.replace_schema_metadata({**(table.schema.metadata or {}), **extra}), plain
        )
        written = Path(work) / "written.parquet"
        source = gpio.read(str(plain)).add_bbox()
        ordered = source.sort_hilbert() if order_by is None else source.sort_column(order_by)
        ordered.write(
            written,
            geoparquet_version=GEOPARQUET_VERSION,
            compression="ZSTD",
            compression_level=COMPRESSION_LEVEL,
            row_group_rows=row_group_size,
        )
        _check_row_groups(written)
        written.replace(out)


def _check_row_groups(path: Path) -> None:
    """Refuse a file with a row group above :data:`MAX_ROW_GROUP_ROWS`."""
    meta = pq.ParquetFile(path).metadata
    largest = max(meta.row_group(i).num_rows for i in range(meta.num_row_groups))
    if largest > MAX_ROW_GROUP_ROWS:
        msg = f"{path.name}: a row group has {largest} rows, more than {MAX_ROW_GROUP_ROWS}"
        raise GeoParquetWriteError(msg)
