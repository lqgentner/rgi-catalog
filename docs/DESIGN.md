# Design decisions

This file records the measured decisions behind the build. The design itself
is in `docs/superpowers/specs/2026-10-22-rgi-mirror-design.md`.

## The catalog is generated

The template expects a hand-edited `catalog/`. This repository generates it.
`pixi run python -m rgi_catalog render` writes `catalog/` from the tracked
files in `metadata/`. A unit test fails when `catalog/` differs from a fresh
render. Edit `metadata/`, never `catalog/`.

## GeoParquet writer

`src/rgi_catalog/geoparquet.py` writes each file in two steps:

1. geopandas writes a plain intermediate GeoParquet file. Its schema
   metadata carries the key-value metadata (`rgi:version`,
   `rgi:mirror_revision`, `rgi:sources`, `rgi:citation`, `rgi:catalog`).
2. The gpio Python API reads that file, adds the bbox covering column,
   orders the rows on the Hilbert curve, and writes the published file in
   one pass. The settings are GeoParquet 2.0, zstd level 19, and the chosen
   row group size. gpio carries the input's non-geo key-value metadata into
   the output (geoparquet-io #690).

gpio does not repair geometries on this path. The build repairs geometries
itself and reports each repair.

gpio rounds a requested row group size above 2,048 to a multiple of 2,048.
Its default writer, DuckDB, treats the result as a target. On the glaciers
table a request of 10,240 rows gives groups of 10,269 to 12,122 rows. The
writer refuses a file with a row group above 150,000 rows, the Portolan cap
(PORTO-FMT-009).

### DuckDB or pyarrow

gpio can also write through pyarrow (its `in-memory` strategy). pyarrow keeps
the row group size exactly, but its file was 9.6% larger: 322.3 MB against
294.2 MB from DuckDB at zstd 15 and the same row group size. Two causes:

- pyarrow tries dictionary encoding on every column. On columns of mostly
  unique values (`rgi_id`, coordinates, the measured floats) it writes the
  dictionary pages and then falls back to plain encoding. That costs about
  0.5 MB per column, 11 MB in all.
- pyarrow writes 1 MB data pages, which zstd compresses less well than
  DuckDB's pages. The geometry column was 16.8 MB larger.

With dictionaries only on repetitive text columns and 8 MB pages, pyarrow
reached 297.7 MB. gpio does not expose those settings, so the build keeps the
DuckDB writer. An exact row group size is not needed.

### Compression level

The full glaciers table through the DuckDB writer, at about 10,000 rows per
group:

| zstd level | File MB | Write s | Local full read s |
| ---: | ---: | ---: | ---: |
| 15 | 294.4 | 100 | 0.17 |
| 17 | 273.7 | 191 | |
| 18 | 258.2 | 221 | |
| 19 | 258.1 | 245 | 0.22 |
| 22 | 258.2 | 282 | 0.22 |

The size falls up to level 18 and stays flat after it. The build uses level
19, the highest standard level. Level 22 gives the same size and only takes
longer. A local full read decompresses about 30% slower than at level 15.
Remote reads depend on the bytes fetched, which are 12% fewer.

### Byte stability

Two writes of the same table give identical bytes.
`tests/unit/test_geoparquet.py::test_write_geoparquet_is_deterministic`
checks this on a 5,000-row table with list and struct columns.

### Readers

`scripts/check_readers.py PATH` reads a file with DuckDB (spatial extension,
a bbox query), geopandas, GDAL through pyogrio, and `gpio check all`. GDAL
needs its Parquet driver, which conda-forge ships as `libgdal-arrow-parquet`.
The pixi environment installs it.

## Glaciers file (measured 2026-10-22)

`convert --products glaciers` writes 274,531 rows. The measurements below
were taken with gpio's default DuckDB writer, before the switch to the
pyarrow writer. At gpio's default of 49,152 rows per group the file was
293.6 MB in 6 row groups.

Readers on the GeoParquet 2.0 file:

| Reader | Result |
| --- | --- |
| DuckDB 1.5.6, spatial bbox query | ok |
| geopandas 1.2.0 | ok, 274,531 rows |
| GDAL 3.13.3 (pyogrio) | ok, 274,531 features |
| `gpio check all` | ok, 40 spec checks passed |

### Row group size

`scripts/check_readers.py --measure` rewrites the file at four sizes and
serves each from a local Range server. The scan is
`SELECT avg(area_km2)` (median of 3 runs, fresh connection each). The
one-glacier read is a bbox query for the first glacier's `cenlon`/`cenlat`.

| Rows per group | Row groups | File MB | Scan s | Scan MB | Scan requests | One glacier MB | One glacier requests |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 27 | 294.6 | 1.071 | 2.61 | 29 | 14.28 | 7 |
| 25,000 | 11 | 292.7 | 1.026 | 2.61 | 13 | 25.03 | 7 |
| 50,000 | 6 | 293.6 | 0.011 | 2.61 | 8 | 61.52 | 7 |
| 100,000 | 3 | 292.9 | 0.010 | 2.61 | 5 | 119.82 | 7 |

The scan reads the same 2.61 MB at every size. Its time steps from about
0.01 s to about 1 s between 8 and 13 requests. That step comes from the
local server or DuckDB's HTTP client, not from the bytes read. On a remote
host each request adds round-trip latency instead.

The one-glacier read fetches the whole geometry column chunk of the matching
row group. Its size grows in proportion to the row group size.

**Decision: about 10,000 rows per group.** The later viewer fetches single
glaciers, and this size makes that read about 4 times cheaper than 50,000.
The cost is about 20 more requests per full scan. The size is below the
50,000 to 150,000 range that the distribution guide recommends. rashid runs
against the data in Task 11.

The final glaciers file is 258.0 MB in 24 row groups of 10,269 to 12,122
rows. The build takes 5 min 28 s and peaks at 5.9 GB of memory. Two builds
from the same inputs gave identical bytes.
