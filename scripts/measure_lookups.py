"""Measure the bytes that a one-glacier read fetches over HTTP.

Usage::

    pixi run python scripts/measure_lookups.py [--product NAME] PATH [PATH ...]

``--product`` is ``glaciers`` (the default), ``complexes``, ``centerlines``
or ``intersects``.
Each file is served from a local server that honours Range requests. The
sample holds one random row of each first-order region (seed 0), taken from
the first file. It also holds Grosser Aletsch Gletscher when the key column
holds its ID. Each sample row is read by the key of its README example:
``rgi_id``, ``rgi_g_id`` for the centerlines, and ``rgi_g_id_1`` or
``rgi_g_id_2`` for the intersects. The read runs alone and
after a ``bbox`` filter. Where the file has the columns, it also runs after
an ``o1region`` or an ``o2region`` filter. geopandas and DuckDB read the
columns of the README example.

The server counts the body bytes it writes, not the ``Content-Length`` it
announces. fsspec closes a connection before the end of a range, so the
announced lengths overstate the transfer. The script prints the median and
the maximum over the sample, in MB.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
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
CASES = ("none", "bbox", "o1region", "o2region")


@dataclass(frozen=True)
class Lookup:
    """The key and the columns of a product's README example.

    A read matches the value of ``key`` in ``key`` or in any column of ``also``.
    """

    key: str
    columns: list[str]
    cases: tuple[str, ...] = CASES
    also: tuple[str, ...] = ()


PRODUCTS = {
    "glaciers": Lookup("rgi_id", ["rgi_id", "display_name", "area_km2", "zmed_m", "geometry"]),
    "complexes": Lookup("rgi_id", ["rgi_id", "area_km2", "glacier_ids", "geometry"]),
    "centerlines": Lookup(
        "rgi_g_id",
        ["rgi_id", "rgi_g_id", "segment_id", "length_m", "geometry"],
        ("none", "bbox"),
    ),
    "intersects": Lookup(
        "rgi_g_id_1",
        ["rgi_id", "rgi_g_id_1", "rgi_g_id_2", "length_m", "geometry"],
        ("none", "bbox"),
        ("rgi_g_id_2",),
    ),
}
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


def sample(path: Path, lookup: Lookup) -> list[dict[str, Any]]:
    """Return one random row of each first-order region, and Aletsch.

    The region is the third field of the key, as in ``RGI2000-v7.0-G-11-02596``.

    Parameters
    ----------
    path
        A GeoParquet file of the product.
    lookup
        The product's key and columns.

    Returns
    -------
    list[dict[str, Any]]
        The key, ``bbox`` and, where the file has them, ``o1region`` and
        ``o2region`` of each sample row.
    """
    names = [lookup.key, "bbox", *(c for c in lookup.cases if c in CASES[2:])]
    rows = pq.read_table(path, columns=names).to_pylist()
    rng = random.Random(0)  # noqa: S311
    by_region: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: r[lookup.key]):
        by_region.setdefault(row[lookup.key].split("-")[3], []).append(row)
    picks = [r for r in rows if r[lookup.key] == ALETSCH][:1]
    picks.extend(rng.choice(by_region[region]) for region in sorted(by_region))
    return picks


def _geopandas(url: str, lookup: Lookup, row: dict[str, Any], case: str) -> int:
    first: list[tuple[str, str, str]] = []
    kwargs: dict[str, Any] = {}
    if case in ("o1region", "o2region"):
        first.append((case, "==", row[case]))
    elif case == "bbox":
        b = row["bbox"]
        kwargs["bbox"] = (b["xmin"], b["ymin"], b["xmax"], b["ymax"])
    filters = [[*first, (k, "==", row[lookup.key])] for k in (lookup.key, *lookup.also)]
    return len(gpd.read_parquet(url, columns=lookup.columns, filters=filters, **kwargs))


def _duckdb(url: str, lookup: Lookup, row: dict[str, Any], case: str) -> int:
    match = " OR ".join(f"{k} = '{row[lookup.key]}'" for k in (lookup.key, *lookup.also))
    where = [f"({match})"]
    if case in ("o1region", "o2region"):
        where.insert(0, f"{case} = '{row[case]}'")
    elif case == "bbox":
        b = row["bbox"]
        where.insert(
            0,
            f"bbox.xmin <= {b['xmax']} AND bbox.xmax >= {b['xmin']} "
            f"AND bbox.ymin <= {b['ymax']} AND bbox.ymax >= {b['ymin']}",
        )
    con = duckdb.connect()
    con.install_extension("httpfs")
    con.load_extension("httpfs")
    con.sql("SET enable_external_file_cache = false")
    columns = ", ".join(lookup.columns)
    query = f"SELECT {columns} FROM read_parquet('{url}') WHERE {' AND '.join(where)}"  # noqa: S608
    return len(con.sql(query).fetchall())


def measure(
    path: Path, lookup: Lookup, rows: list[dict[str, Any]]
) -> dict[tuple[str, str], list[int]]:
    """Read each sample row in each case with each reader and count the bytes.

    Parameters
    ----------
    path
        A GeoParquet file of the product.
    lookup
        The product's key and columns.
    rows
        The sample, from :func:`sample`.

    Returns
    -------
    dict[tuple[str, str], list[int]]
        The bytes fetched per read, by reader and case.

    Raises
    ------
    RuntimeError
        If a read returns no row.
    """
    fetched: dict[tuple[str, str], list[int]] = {}
    with _serve(path.parent) as base:
        url = f"{base}/{path.name}"
        for row in rows:
            for case in lookup.cases:
                for reader, read in (("geopandas", _geopandas), ("duckdb", _duckdb)):
                    _CountingHandler.bytes_sent = 0
                    if not read(url, lookup, row, case):
                        msg = f"{reader} {case} {row[lookup.key]}: no rows"
                        raise RuntimeError(msg)
                    fetched.setdefault((reader, case), []).append(_CountingHandler.bytes_sent)
    return fetched


def main() -> None:
    """Print the median and maximum MB of each reader and case for each file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", choices=sorted(PRODUCTS), default="glaciers")
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    lookup = PRODUCTS[args.product]
    rows = sample(args.paths[0], lookup)
    print(f"{'file':<32} {'reader':<10} " + " ".join(f"{c:>15}" for c in lookup.cases))
    for path in args.paths:
        fetched = measure(path, lookup, rows)
        for reader in ("geopandas", "duckdb"):
            cells = []
            for case in lookup.cases:
                values = fetched[reader, case]
                cells.append(f"{statistics.median(values) / 1e6:6.1f} / {max(values) / 1e6:5.1f}")
            print(f"{path.name:<32} {reader:<10} " + " ".join(f"{c:>15}" for c in cells))


if __name__ == "__main__":
    main()
