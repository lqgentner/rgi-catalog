"""The glacier names table: the IDs and names of the glaciers file, without the outlines.

A client that searches glaciers by name or ID reads this one small file
instead of three columns across every row group of the glaciers file. The
table has the rows of the glaciers file in the same order, so row ``i`` of
one is row ``i`` of the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow.parquet as pq

from rgi_catalog.geoparquet import COMPRESSION_LEVEL, MAX_ROW_GROUP_ROWS
from rgi_catalog.paths import version_dir

if TYPE_CHECKING:
    from pathlib import Path

# The collection whose GeoParquet file the table comes from.
COLLECTION = "glaciers"
# The asset key of the table in that collection.
ASSET = "names"
COLUMNS = ("rgi_id", "display_name", "glac_name", "o1region", "o2region")
# The rgi_id values count up by one, so each value differs from the one before
# in its last characters only. The names are mostly unique, and a length
# delta packs them smaller than a dictionary. docs/DESIGN.md has the sizes.
ENCODINGS = {
    "rgi_id": "DELTA_BYTE_ARRAY",
    "display_name": "DELTA_LENGTH_BYTE_ARRAY",
    "glac_name": "DELTA_LENGTH_BYTE_ARRAY",
}
DICTIONARY = ["o1region", "o2region"]
# The table carries the footer keys of the glaciers file with this prefix. It
# has no geometry, so it leaves out the GeoParquet ``geo`` key.
KV_PREFIX = b"rgi:"


def names_path(staging: Path, version: str) -> Path:
    """Return the staged names table of a version.

    Parameters
    ----------
    staging
        The staging root.
    version
        The RGI version.

    Returns
    -------
    Path
        ``staging/v{version}/glaciers/rgi{version}-glacier-names.parquet``.
    """
    return staging / version_dir(version) / COLLECTION / f"rgi{version}-glacier-names.parquet"


def write_names_table(glaciers: Path, out: Path) -> Path:
    """Write the names table from the glaciers file.

    Parameters
    ----------
    glaciers
        The glaciers GeoParquet file.
    out
        The plain Parquet file to write.

    Returns
    -------
    Path
        ``out``.
    """
    table = pq.read_table(glaciers, columns=list(COLUMNS))
    kv = {k: v for k, v in (table.schema.metadata or {}).items() if k.startswith(KV_PREFIX)}
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table.replace_schema_metadata(kv),
        out,
        compression="zstd",
        compression_level=COMPRESSION_LEVEL,
        row_group_size=MAX_ROW_GROUP_ROWS,
        use_dictionary=DICTIONARY,
        column_encoding=ENCODINGS,
    )
    return out
