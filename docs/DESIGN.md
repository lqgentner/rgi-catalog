# Design decisions

This file records the measured decisions behind the build. The design itself
is in `docs/superpowers/specs/2026-10-22-rgi-mirror-design.md`.

## The catalog is generated

The template expects a hand-edited `catalog/`. This repository generates it.
`pixi run python -m rgi_catalog render` writes `catalog/` from the tracked
files in `metadata/`. A unit test fails when `catalog/` differs from a fresh
render. Edit `metadata/`, never `catalog/`.

## GeoParquet writer

`src/rgi_catalog/geoparquet.py` writes each file in three steps:

1. geopandas writes a plain intermediate GeoParquet file.
2. `gpio convert geoparquet` writes the published file. The settings are
   GeoParquet 2.0, zstd level 15, Hilbert order, and the chosen row group
   size. `--no-repair-geometry` stops gpio from changing a geometry. The
   build repairs geometries itself and reports each repair.
3. `gpio add bbox` adds the bbox covering column when step 2 did not.

The key-value metadata (`rgi:version`, `rgi:mirror_revision`, `rgi:sources`,
`rgi:citation`, `rgi:catalog`) goes into the Parquet footer last. The build
uses `geoparquet_io.core.parquet_footer.patch_footer_kv` from the pinned
geoparquet-io 1.7.0. That function rewrites only the footer, so the data
pages keep their zstd level 15 encoding.

gpio snaps `--row-group-size` down to a multiple of 2,048 rows.

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

`convert --products glaciers` writes 274,531 rows. At the gpio default of
49,152 rows per group the file is 293.6 MB in 6 row groups. The build takes
3 min 23 s and peaks at 3.9 GB of memory.

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

The decision is pending with the author.
