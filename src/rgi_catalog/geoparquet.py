"""Write GeoParquet through gpio (geoparquet-io), as design §5.5 sets out.

geopandas writes a plain intermediate file. ``gpio convert geoparquet`` then
writes the published file: GeoParquet 2.0, zstd level 15, Hilbert order, a
bbox covering column, and the chosen row group size. The key-value metadata
goes into the footer last, without re-encoding a page.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Literal

from geoparquet_io.core.parquet_footer import patch_footer_kv
import pyarrow.parquet as pq

if TYPE_CHECKING:
    import geopandas as gpd

GEOPARQUET_VERSION: Literal["2.0", "1.1"] = "2.0"
ROW_GROUP_SIZE: int = 49_152
COMPRESSION_LEVEL = 15
KV_KEYS = ("rgi:version", "rgi:mirror_revision", "rgi:sources", "rgi:citation", "rgi:catalog")


class GpioError(Exception):
    """A gpio command failed."""


def _gpio(*args: str) -> None:
    exe = shutil.which("gpio")
    if exe is None:
        msg = "gpio is not on PATH; run inside the pixi environment"
        raise GpioError(msg)
    result = subprocess.run([exe, *args], capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        msg = f"gpio {' '.join(args[:2])} failed:\n{result.stdout}\n{result.stderr}"
        raise GpioError(msg)


def write_geoparquet(
    gdf: gpd.GeoDataFrame,
    out: Path,
    *,
    kv: dict[str, str],
    row_group_size: int = ROW_GROUP_SIZE,
) -> None:
    """Write a GeoDataFrame as published GeoParquet.

    Parameters
    ----------
    gdf
        The table, in EPSG:4326 with 2D geometries.
    out
        The destination. It is replaced only once the new file is complete.
    kv
        Footer key-value metadata. Must hold every key in :data:`KV_KEYS`.
    row_group_size
        The maximum rows per row group. gpio snaps it down to a multiple of
        2,048.

    Raises
    ------
    ValueError
        If ``kv`` lacks a key of :data:`KV_KEYS`.
    """
    if missing := [k for k in KV_KEYS if k not in kv]:
        msg = f"kv metadata lacks {missing}"
        raise ValueError(msg)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=f".{out.stem}-") as work:
        plain = Path(work) / "plain.parquet"
        converted = Path(work) / "converted.parquet"
        gdf.to_parquet(plain, index=False)
        _gpio(
            "convert",
            "geoparquet",
            str(plain),
            str(converted),
            "--geoparquet-version",
            GEOPARQUET_VERSION,
            "--no-repair-geometry",
            "--compression",
            "zstd",
            "--compression-level",
            str(COMPRESSION_LEVEL),
            "--row-group-size",
            str(row_group_size),
        )
        if "bbox" not in pq.read_schema(converted).names:
            with_bbox = Path(work) / "bbox.parquet"
            _gpio(
                "add",
                "bbox",
                str(converted),
                str(with_bbox),
                "--compression-level",
                str(COMPRESSION_LEVEL),
                "--row-group-size",
                str(row_group_size),
            )
            converted = with_bbox
        final = Path(work) / "final.parquet"
        patch_footer_kv(str(converted), dict(kv), output_file=str(final))
        final.replace(out)
