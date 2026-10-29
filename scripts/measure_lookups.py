"""Measure the bytes that a one-glacier read fetches over HTTP.

Usage::

    pixi run python scripts/measure_lookups.py PATH [PATH ...]

Each file is served from a local server that honours Range requests. The
sample is Grosser Aletsch Gletscher and one random glacier of each
first-order region (seed 0), taken from the first file. Each glacier is read
by its ``rgi_id`` four times: alone, and after a ``bbox``, an ``o1region``
or an ``o2region`` filter. geopandas and DuckDB read the columns of the
glaciers README example.

The server counts the body bytes it writes, not the ``Content-Length`` it
announces. fsspec closes a connection before the end of a range, so the
announced lengths overstate the transfer. The script prints the median and
the maximum over the sample, in MB.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import random
import socket
import statistics
import threading
from typing import TYPE_CHECKING, Any, override

import duckdb
import geopandas as gpd
import pyarrow.parquet as pq

from rgi_catalog.preview import RangeHandler, serve

if TYPE_CHECKING:
    from collections.abc import Iterator

ALETSCH = "RGI2000-v7.0-G-11-02596"
COLUMNS = ["rgi_id", "display_name", "area_km2", "zmed_m", "geometry"]
CASES = ("none", "bbox", "o1region", "o2region")
# The send buffer of each connection. A small buffer limits the bytes that
# the kernel accepts for a client that has closed the connection.
SEND_BUFFER = 65_536


class _CountingHandler(RangeHandler):
    """Count the body bytes that the preview server writes."""

    bytes_sent = 0

    @override
    def setup(self) -> None:
        super().setup()
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER)
        raw = self.wfile

        class _Writer:
            def write(self, data: bytes) -> int:
                n = raw.write(data)
                _CountingHandler.bytes_sent += len(data)
                return n

            def __getattr__(self, name: str) -> Any:
                return getattr(raw, name)

        self.wfile = _Writer()  # type: ignore[assignment]


@contextmanager
def _serve(root: Path) -> Iterator[str]:
    server = serve(root, port=0, handler=_CountingHandler)
    server.handle_error = lambda *_: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def sample(path: Path) -> list[dict[str, Any]]:
    """Return Aletsch and one random glacier of each first-order region.

    Parameters
    ----------
    path
        A glaciers GeoParquet file.

    Returns
    -------
    list[dict[str, Any]]
        The ``rgi_id``, ``o1region``, ``o2region`` and ``bbox`` of each glacier.
    """
    rows = pq.read_table(path, columns=["rgi_id", "o1region", "o2region", "bbox"]).to_pylist()
    rng = random.Random(0)  # noqa: S311
    by_region: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: r["rgi_id"]):
        by_region.setdefault(row["o1region"], []).append(row)
    picks = [r for r in rows if r["rgi_id"] == ALETSCH]
    picks.extend(rng.choice(by_region[region]) for region in sorted(by_region))
    return picks


def _geopandas(url: str, glacier: dict[str, Any], case: str) -> int:
    filters: list[tuple[str, str, str]] = [("rgi_id", "==", glacier["rgi_id"])]
    kwargs: dict[str, Any] = {}
    if case in ("o1region", "o2region"):
        filters.insert(0, (case, "==", glacier[case]))
    elif case == "bbox":
        b = glacier["bbox"]
        kwargs["bbox"] = (b["xmin"], b["ymin"], b["xmax"], b["ymax"])
    return len(gpd.read_parquet(url, columns=COLUMNS, filters=filters, **kwargs))


def _duckdb(url: str, glacier: dict[str, Any], case: str) -> int:
    where = [f"rgi_id = '{glacier['rgi_id']}'"]
    if case in ("o1region", "o2region"):
        where.insert(0, f"{case} = '{glacier[case]}'")
    elif case == "bbox":
        b = glacier["bbox"]
        where.insert(
            0,
            f"bbox.xmin <= {b['xmax']} AND bbox.xmax >= {b['xmin']} "
            f"AND bbox.ymin <= {b['ymax']} AND bbox.ymax >= {b['ymin']}",
        )
    con = duckdb.connect()
    con.install_extension("httpfs")
    con.load_extension("httpfs")
    con.sql("SET enable_external_file_cache = false")
    query = f"SELECT {', '.join(COLUMNS)} FROM read_parquet('{url}') WHERE {' AND '.join(where)}"  # noqa: S608
    return len(con.sql(query).fetchall())


def measure(path: Path, glaciers: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    """Read each glacier in each case with each reader and count the bytes.

    Parameters
    ----------
    path
        A glaciers GeoParquet file.
    glaciers
        The sample, from :func:`sample`.

    Returns
    -------
    dict[tuple[str, str], list[int]]
        The bytes fetched per read, by reader and case.

    Raises
    ------
    RuntimeError
        If a read does not return exactly one row.
    """
    fetched: dict[tuple[str, str], list[int]] = {}
    with _serve(path.parent) as base:
        url = f"{base}/{path.name}"
        for glacier in glaciers:
            for case in CASES:
                for reader, read in (("geopandas", _geopandas), ("duckdb", _duckdb)):
                    _CountingHandler.bytes_sent = 0
                    if (rows := read(url, glacier, case)) != 1:
                        msg = f"{reader} {case} {glacier['rgi_id']}: {rows} rows"
                        raise RuntimeError(msg)
                    fetched.setdefault((reader, case), []).append(_CountingHandler.bytes_sent)
    return fetched


def main() -> None:
    """Print the median and maximum MB of each reader and case for each file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    glaciers = sample(args.paths[0])
    print(f"{'file':<32} {'reader':<10} " + " ".join(f"{c:>15}" for c in CASES))
    for path in args.paths:
        fetched = measure(path, glaciers)
        for reader in ("geopandas", "duckdb"):
            cells = []
            for case in CASES:
                values = fetched[reader, case]
                cells.append(f"{statistics.median(values) / 1e6:6.1f} / {max(values) / 1e6:5.1f}")
            print(f"{path.name:<32} {reader:<10} " + " ".join(f"{c:>15}" for c in cells))


if __name__ == "__main__":
    main()
