"""Check that every reader in the chain opens a GeoParquet file, and measure row group sizes.

Usage::

    pixi run python scripts/check_readers.py PATH            # reader matrix
    pixi run python scripts/check_readers.py PATH --measure  # row group measurements

The reader matrix reads the file with DuckDB (spatial extension, a bbox
query), geopandas, GDAL (through pyogrio) and ``gpio check all``.

``--measure`` rewrites the file at several row group sizes and serves each
over HTTP from a local server that honours Range requests. For each size it
reports (a) the wall time of a DuckDB ``avg(area_km2)`` over HTTP and (b) the
bytes fetched to read one glacier by its bbox.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from typing import TYPE_CHECKING, override

import duckdb
import geopandas as gpd
import pyarrow.parquet as pq
import pyogrio

from rgi_catalog.geoparquet import KV_KEYS, write_geoparquet
from rgi_catalog.preview import RangeHandler, serve

if TYPE_CHECKING:
    from collections.abc import Iterator

SIZES = (10_000, 25_000, 50_000, 100_000)


class _CountingHandler(RangeHandler):
    """Count the requests and the body bytes the preview server sends."""

    bytes_sent = 0
    requests = 0

    @override
    def send_header(self, keyword: str, value: str) -> None:
        if keyword == "Content-Length" and self.command == "GET":
            type(self).bytes_sent += int(value)
            type(self).requests += 1
        super().send_header(keyword, value)


@contextmanager
def _serve(root: Path) -> Iterator[str]:
    server = serve(root, port=0, handler=_CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _duckdb() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for ext in ("spatial", "httpfs"):
        con.install_extension(ext)
        con.load_extension(ext)
    return con


def _probe_point(path: Path) -> tuple[float, float]:
    table = pq.read_table(path, columns=["cenlon", "cenlat"]).slice(0, 1).to_pylist()[0]
    return float(table["cenlon"]), float(table["cenlat"])


def _bbox_query(source: str, lon: float, lat: float) -> str:
    return (
        f"SELECT count(*) FROM read_parquet('{source}') "  # noqa: S608
        f"WHERE bbox.xmin <= {lon} AND bbox.xmax >= {lon} "
        f"AND bbox.ymin <= {lat} AND bbox.ymax >= {lat} "
        f"AND ST_Intersects(geometry, ST_Point({lon}, {lat}))"
    )


def reader_matrix(path: Path) -> list[tuple[str, str]]:
    """Read the file with every reader and report ``ok`` or the error.

    Parameters
    ----------
    path
        A GeoParquet file.

    Returns
    -------
    list[tuple[str, str]]
        One ``(reader, result)`` pair per reader.
    """
    lon, lat = _probe_point(path)
    results: list[tuple[str, str]] = []

    def attempt(name: str, check: object) -> None:
        try:
            detail = check()  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001
            results.append((name, f"error: {exc}".splitlines()[0][:200]))
        else:
            results.append((name, f"ok ({detail})"))

    attempt(
        "duckdb spatial bbox query",
        lambda: f"{_duckdb().sql(_bbox_query(str(path), lon, lat)).fetchone()[0]} row(s)",
    )
    attempt("geopandas read_parquet", lambda: f"{len(gpd.read_parquet(path))} rows")
    attempt(
        "GDAL (pyogrio.read_info)",
        lambda: f"{pyogrio.read_info(path)['features']} features",
    )

    def gpio_check() -> str:
        exe = shutil.which("gpio") or "gpio"
        done = subprocess.run(
            [exe, "check", "all", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise RuntimeError(done.stdout[-500:] + done.stderr[-500:])
        return "exit 0"

    attempt("gpio check all", gpio_check)
    return results


def measure(path: Path) -> list[dict[str, float]]:
    """Rewrite the file at each size in :data:`SIZES` and time two reads over HTTP.

    The rewrite goes through :func:`rgi_catalog.geoparquet.write_geoparquet`,
    the same path the build uses.

    Parameters
    ----------
    path
        A GeoParquet file with ``area_km2``, ``cenlon`` and ``cenlat`` columns.

    Returns
    -------
    list[dict[str, float]]
        Per size: the requested size, the row groups written, the file size,
        the scan time in seconds, and the bytes fetched for one glacier.
    """
    lon, lat = _probe_point(path)
    source = gpd.read_parquet(path).drop(columns="bbox", errors="ignore")
    footer = pq.ParquetFile(path).metadata.metadata or {}
    kv = {k.decode(): v.decode() for k, v in footer.items() if k.decode() in KV_KEYS}
    rows: list[dict[str, float]] = []
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        for size in SIZES:
            out = root / f"rg{size}.parquet"
            write_geoparquet(source, out, kv=kv, row_group_size=size)
            groups = pq.ParquetFile(out).metadata.num_row_groups
            with _serve(root) as base:
                url = f"{base}/{out.name}"
                scans = []
                for _ in range(3):
                    con = _duckdb()
                    con.sql("SET enable_external_file_cache = false")
                    _CountingHandler.bytes_sent = 0
                    _CountingHandler.requests = 0
                    start = time.perf_counter()
                    con.sql(f"SELECT avg(area_km2) FROM read_parquet('{url}')").fetchone()  # noqa: S608
                    scans.append(time.perf_counter() - start)
                scan = statistics.median(scans)
                scan_mb = _CountingHandler.bytes_sent / 1e6
                scan_requests = _CountingHandler.requests
                con = _duckdb()
                con.sql("SET enable_external_file_cache = false")
                _CountingHandler.bytes_sent = 0
                _CountingHandler.requests = 0
                found = con.sql(_bbox_query(url, lon, lat)).fetchone()
                fetched = _CountingHandler.bytes_sent
            rows.append(
                {
                    "rows_per_group": size,
                    "row_groups": groups,
                    "file_mb": out.stat().st_size / 1e6,
                    "scan_s": scan,
                    "scan_mb": scan_mb,
                    "scan_requests": scan_requests,
                    "one_glacier_requests": _CountingHandler.requests,
                    "one_glacier_mb": fetched / 1e6,
                    "matches": float(found[0]) if found else 0.0,
                },
            )
    return rows


def main() -> None:
    """Run the reader matrix, or the measurements with ``--measure``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--measure", action="store_true")
    args = parser.parse_args()
    if args.measure:
        print(
            "rows/group  groups  file MB  scan s (median of 3)  scan MB  scan req"
            "  one-glacier MB  one-glacier req",
        )
        for r in measure(args.path):
            print(
                f"{r['rows_per_group']:>10,.0f}  {r['row_groups']:>6.0f}  {r['file_mb']:>7.1f}"
                f"  {r['scan_s']:>20.3f}  {r['scan_mb']:>7.2f}  {r['scan_requests']:>8.0f}"
                f"  {r['one_glacier_mb']:>14.2f}  {r['one_glacier_requests']:>15.0f}",
            )
        return
    width = max(len(name) for name, _ in reader_matrix(args.path))
    for name, result in reader_matrix(args.path):
        print(f"{name:<{width}}  {result}")


if __name__ == "__main__":
    main()
