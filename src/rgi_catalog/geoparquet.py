"""Write GeoParquet through gpio (geoparquet-io), as design §5.5 sets out.

geopandas writes a plain intermediate file that carries the key-value
metadata. gpio's Python API then adds the bbox covering column, orders the
rows on the Hilbert curve and writes the published file in one pass:
GeoParquet 2.0, zstd level 15 and the chosen row group size. gpio carries the
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

# The pyarrow writer. gpio's default DuckDB writer overshoots the requested
# row group size by up to 18% on the full glaciers table.
WRITE_STRATEGY = "in-memory"
GEOPARQUET_VERSION: Literal["2.0", "1.1"] = "2.0"
# 10,000 rows, rounded up to whole 2,048-row vectors. docs/DESIGN.md has the
# measurements.
ROW_GROUP_SIZE: int = 10_240
COMPRESSION_LEVEL = 15
VECTOR = 2_048
KV_KEYS = ("rgi:version", "rgi:mirror_revision", "rgi:sources", "rgi:citation", "rgi:catalog")


class GeoParquetWriteError(Exception):
    """A written file breaks a setting it was written with."""


def write_geoparquet(
    gdf: gpd.GeoDataFrame,
    out: Path,
    *,
    kv: dict[str, str],
    row_group_size: int = ROW_GROUP_SIZE,
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
        The maximum rows per row group. gpio snaps a value above 2,048 to a
        multiple of 2,048.

    Raises
    ------
    ValueError
        If ``kv`` lacks a key of :data:`KV_KEYS`.
    GeoParquetWriteError
        If a written row group is larger than requested.
    """
    if missing := [k for k in KV_KEYS if k not in kv]:
        msg = f"kv metadata lacks {missing}"
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
        gpio.read(str(plain)).add_bbox().sort_hilbert().write(
            written,
            geoparquet_version=GEOPARQUET_VERSION,
            compression="ZSTD",
            compression_level=COMPRESSION_LEVEL,
            row_group_rows=row_group_size,
            write_strategy=WRITE_STRATEGY,
        )
        _check_row_groups(written, row_group_size)
        written.replace(out)


def _check_row_groups(path: Path, row_group_size: int) -> None:
    """Refuse a file whose row groups exceed the requested size (rounded up to 2,048 rows)."""
    limit = row_group_size if row_group_size <= VECTOR else -(-row_group_size // VECTOR) * VECTOR
    meta = pq.ParquetFile(path).metadata
    largest = max(meta.row_group(i).num_rows for i in range(meta.num_row_groups))
    if largest > limit:
        msg = f"{path.name}: a row group has {largest} rows, more than {limit}"
        raise GeoParquetWriteError(msg)
