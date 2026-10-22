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
