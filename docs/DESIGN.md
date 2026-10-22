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

## Web-map archive

`src/rgi_catalog/tiles.py` builds `v7.0/glaciers/rgi7.0.pmtiles` from the
staged glaciers file. The tiler is tylertoo 0.8.0.

### The tylertoo binary

The PyPI wheel of tylertoo 0.8.0 has only the Python API. That API writes one
layer per archive and has no `pyramid`, `--entry-zoom` or
`--include-property`. The build uses the release binary instead
(`tylertoo-0.8.0-x86_64-unknown-linux-musl.tar.gz`). `tiles.TYLERTOO` pins it
by sha256, and `sources.fetch` verifies it into `.cache/`.

The 0.8.0 binary lacks two flags that the online documentation lists:
`--size-valve` and `--name`/`--attribution`/`--description` on `tiles` and
`pyramid`. The build writes the archive metadata itself
(`tiles.set_metadata`). It copies the header, directories and tile data byte
for byte and replaces only the metadata block.

### How the archive is built

1. `write_labels` writes one point per glacier with a `display_name`, at
   RGI's own `cenlon`/`cenlat`, to `staging/v7.0/.tiles/labels.parquet`.
2. `tylertoo tiles` builds each zoom band of each layer into its own archive.
3. `tylertoo pyramid --band LO-HI:ARCHIVE:LAYER …` joins the bands. Bands of
   different layers may share zooms. Each band's label must equal its layer
   name, or `pyramid` refuses the build.

| Layer | Band | Settings |
| --- | --- | --- |
| `glaciers` | z0–9 | tylertoo defaults: density budget, cell thinning, 500 KB tile cap |
| `glaciers` | z10–12 | `--no-density-drop --polygon-thinning 0 --polygon-visibility 0 --simplify-factor 0.5` |
| `glacier-labels` | z7–12 | `--entry-zoom label_minzoom:7=7,…,12=12 --no-density-drop` |

Every band uses `--no-simple-clip-fastpath` and `--include-property` for
each scalar column (`tile_properties`). List and struct columns
(`hypso_permille`, `rgi6_links`, `bbox`) stay out. tylertoo would write them
as JSON strings. Timestamps become strings in the tiles.

A band marked `complete` must keep every feature at every zoom, or every
feature that has entered by that zoom for the label layer. The build reads
each band's tylertoo report and fails otherwise.

### Findings that set the flags

Measured on the full glaciers table:

- With tylertoo defaults, the Alps keep 550 of 4,079 glaciers at z10. The
  density budget thins polygons, unlike tippecanoe's default.
  `--no-density-drop` keeps all of them there.
- Worldwide, cell thinning (`--polygon-thinning`, default 1 GSD) still drops
  4 glaciers at z10. With it off, simplification at 1 GSD collapses two
  slivers of about 0.01 km² and 80 m width (`RGI2000-v7.0-G-02-15948`,
  `RGI2000-v7.0-G-17-28135`). `--simplify-factor 0.5` keeps them.
- Labels with `--entry-zoom` alone appear from their entry zoom but are
  thinned after it (Alps z12: 981 of 1,005). `--no-density-drop` keeps all.

### Zoom range

The first build went to z14 and was 2.4 GB. z14 alone was 2.2 million tiles,
mostly about 1 KB each: tiles inside ice caps that carry one clipped polygon
and its 39 properties. A z12 tile resolves about 2.4 m at the equator, finer
than the imagery behind the outlines, and clients overzoom above it. Every
layer therefore stops at z12, because a client overzooms one source as a
whole.

Leaving the four long submission text columns out of the tiles saves 12% of
the z10–12 band (550 to 485 MB). The tiles keep every scalar column.

The glaciers layer starts at z0, so the default style shows data at the full
extent. Below z10 the tiler thins by density. z9 keeps all 274,531 glaciers.

### Result (measured 2026-10-22)

`tiles --version 7.0` takes 80 s and peaks at 2.7 GB of memory. The archive
is 759.0 MB. Two builds gave identical bytes.

| z | Tiles | MB | p50 bytes | Max bytes |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 0.03 | 25,678 | 25,678 |
| 2 | 15 | 0.4 | 14,943 | 161,175 |
| 4 | 91 | 3.2 | 8,178 | 257,923 |
| 6 | 471 | 13.1 | 7,843 | 299,884 |
| 8 | 2,796 | 41.8 | 4,578 | 289,538 |
| 9 | 7,482 | 101.8 | 4,003 | 266,007 |
| 10 | 20,895 | 104.8 | 1,994 | 95,433 |
| 11 | 61,700 | 161.0 | 1,398 | 51,611 |
| 12 | 192,849 | 328.2 | 1,123 | 33,401 |

Decoded counts: 274,531 glaciers at z10, z11 and z12. Labels: 244 at z7,
714 at z8, 1,462 at z9, 2,715 at z10, 4,514 at z11 and all 9,467 at z12.
Each equals the number of named glaciers whose `label_minzoom` has been
reached.

`label_minzoom` falls by one zoom for every factor of 4 in area, because
each zoom step quadruples a glacier's area on screen. A glacier of 1 km²
gets its label at z11. The result is clamped to z7–z12.
