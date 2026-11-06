# Design decisions

This file records the measured decisions behind the build.

## The catalog is generated

The template expects a hand-edited `catalog/`. This repository generates it.
`pixi run python -m rgi_catalog render` writes `catalog/` from the tracked
files in `metadata/`. A unit test fails when `catalog/` differs from a fresh
render. Edit `metadata/`, never `catalog/`.

`render --version 7.0` first measures the staged files into
`metadata/builds/v7.0.json`: sizes, checksums, extents, row counts, schemas,
and the archive's layers. The record keeps its `updated` time when nothing
else changed, so a second render changes nothing. `render --no-record` renders from the
committed record alone, which is how CI and the drift test run.

`metadata/columns.yaml` describes each column of each collection. The
entries of the RGI columns started as a copy of the text in RGI's
`attributes_metadata.json` of each product. Those files are the same in
every region. A description can be reworded in `columns.yaml`.
`pixi run python -m rgi_catalog columns --version 7.0` lists each
description that differs from RGI's text.

The data is in `staging/`, not beside `catalog/`, so the `gates` task
sets `CI_LIGHT=1` as CI does, and `tests/test_links.py` exempts
data hrefs of links as well as of assets, because the `rel: pmtiles` link
points at data. The preview tree checks every href with the data present.

The upstream files are `related` links, not `source` assets. A `via` link
must be an HTML page (PTL-PRO-001), so `via` names only the NSIDC landing page. The browser lists
them under the additional resources and does not offer them as data of the
collection. The NSIDC zips need an Earthdata login. The `rgi6_links` CSV
does not, so PORTO-FMT-002 recommends a `source` asset for it. This is a
SHOULD, and the catalog does not follow it for the CSV.

The web map archive is a `visual` asset and a `rel: pmtiles` link. The
spec requires the link. The browser draws a collection only from its
assets. Without the asset it falls back to the GeoParquet file.

## GeoParquet writer

`src/rgi_catalog/geoparquet.py` writes each file in two steps:

1. geopandas writes a plain intermediate GeoParquet file. Its schema
   metadata carries the key-value metadata (`rgi:version`,
   `rgi:mirror_revision`, `rgi:sources`, `rgi:citation`, `rgi:catalog`).
2. The gpio Python API reads that file, adds the bbox covering column,
   orders the rows, and writes the published file in one pass. The rows
   follow the Hilbert curve, or the column that the collection's `layout`
   in `metadata/catalog.yaml` names. The settings are GeoParquet 2.0, zstd level 19, and the chosen
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
294.2 MB from DuckDB at zstd 15 and the same row group size. The causes:

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

The size falls up to level 18 and does not change after it. The build uses level
19, the highest standard level. Level 22 gives the same size and only takes
longer. A local full read decompresses about 30% slower than at level 15.
Remote reads depend on the bytes fetched, which are 12% fewer.

### Byte stability

Repeated writes of the same table give identical bytes.
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

The glaciers file was 258.0 MB in 24 row groups of 10,269 to 12,122 rows.
The build took 5 min 28 s and peaked at 5.9 GB of memory. A second build from
the same inputs gave identical bytes. The next section replaces this layout for
the glaciers. The other products keep it.

### Row order (measured 2026-10-29)

Issue #1 reports that a geopandas read of one glacier fetches a large part of
the Hilbert-ordered file. The glaciers file is now in `rgi_id` order in row
groups of 4,096 rows. A geopandas read of one glacier fetches 6 to 15 MB at
the median, against 56 to 120 MB before.

`scripts/measure_lookups.py` serves each candidate file from a local Range
server. The sample is Grosser Aletsch Gletscher (`RGI2000-v7.0-G-11-02596`)
and one random glacier of each first-order region. geopandas 1.2.0 (pyarrow
25.0.0, fsspec) and DuckDB 1.5.6 read each glacier by `rgi_id` with the
columns of the README example. Each read has one of four filters before the
`rgi_id` filter: none, a `bbox`, an `o1region` or an `o2region`.

The server counts the body bytes that it writes. fsspec closes connections
before the end of a range, so the announced `Content-Length` overstates a
geopandas read by a factor of about 5. For DuckDB the two counts are equal.

geopandas, MB fetched for one glacier, median / maximum over 20 glaciers:

| Layout | Rows per group | none | bbox | o1region | o2region |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hilbert | 10,240 | 115.7 / 200.9 | 55.8 / 87.5 | 120.0 / 199.9 | 118.9 / 205.7 |
| Hilbert, page index | 10,240 | 124.8 / 215.7 | 56.8 / 88.5 | 121.3 / 204.4 | 122.2 / 203.0 |
| `o1region`, then Hilbert | 10,240 | 21.3 / 94.2 | 22.7 / 99.3 | 24.5 / 106.2 | 27.1 / 94.2 |
| `o2region`, then Hilbert | 10,240 | 21.9 / 89.0 | 23.2 / 104.6 | 21.2 / 106.3 | 21.1 / 111.3 |
| `rgi_id` | 10,240 | 19.9 / 33.8 | 20.2 / 34.1 | 18.9 / 33.8 | 18.1 / 39.1 |
| `rgi_id` | 4,096 | 8.0 / 27.3 | 14.6 / 33.4 | 5.7 / 22.8 | 5.7 / 38.6 |
| `rgi_id` | 2,048 | 6.0 / 16.5 | 13.0 / 18.6 | 6.0 / 13.3 | 6.0 / 13.3 |

DuckDB, MB fetched for one glacier, median / maximum over the four filters:

| Layout | Rows per group | MB |
| --- | ---: | ---: |
| Hilbert | 10,240 | 10.0 / 23.6 |
| `o2region`, then Hilbert | 10,240 | 11.1 / 20.9 |
| `rgi_id` | 10,240 | 11.1 / 24.1 |
| `rgi_id` | 4,096 | 4.9 / 13.4 |
| `rgi_id` | 2,048 | 3.9 / 9.2 |

The `rgi_id` layouts, by file size, footer size and a DuckDB
`SELECT avg(area_km2)` scan (median of 3 runs):

| Layout | Rows per group | Row groups | File MB | Footer KB | Scan s | Scan MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Hilbert | 10,240 | 24 | 258.0 | 145 | 1.076 | 2.62 |
| `rgi_id` | 10,240 | 27 | 258.0 | 165 | 1.066 | 2.62 |
| `rgi_id` | 4,096 | 68 | 261.4 | 404 | 1.063 | 3.44 |
| `rgi_id` | 2,048 | 135 | 265.3 | 795 | 1.057 | 4.26 |

Findings:

- **The page index has no effect.** pyarrow and DuckDB do not use it. The
  test file has column indexes for `rgi_id`, `o1region` and `o2region`. Both
  readers fetch the same bytes as from the same file without them.
- **The Hilbert order defeats the `rgi_id` statistics.** Each row group spans
  many regions, so an `rgi_id` filter selects many row groups. A region
  filter selects as many.
- **`rgi_id` order gives each row group a separate range of `rgi_id`.** A
  filter on one `rgi_id` selects one row group. RGI numbers the glaciers by
  second-order region and then by neighbour. The median step between
  consecutive glaciers is 0.006° in longitude in region 13. So the order is
  spatial, and the bbox reads also improve.
- **geopandas fetches about twice the projected column chunks of a row
  group.** pyarrow reads each column chunk through fsspec, which reads ahead
  by 5 MB, and the ranges overlap. The row group size sets the remaining
  cost.
- **A read of one region falls.** geopandas fetches 98.0 MB for `rgi_id` and
  `geometry` of region 11 from the Hilbert file and 13.0 MB from the
  `rgi_id` file at 4,096 rows.

**Decision: `rgi_id` order, 4,096 rows per group.** The median geopandas read
falls by a factor of 14 to 21 without a bbox filter, and by a factor of 3.8
with one. At 2,048 rows the median does not
fall further and the footer doubles. The scan time does not change.
PTL-DAT-006 requires spatially ordered rows. The row groups average 1.8% of
the file extent, against 4.7% for the Hilbert file and the 30% limit.

The glaciers file is 261.4 MB in 68 row groups of up to 4,096 rows. The
build takes 5 min 9 s. The schema and the rows equal those of the Hilbert
file.

### The other products in `rgi_id` order (measured 2026-10-29)

The complexes and the centerlines use the glaciers layout: `rgi_id` order in
row groups of 4,096 rows. The intersects use `rgi_id` order in row groups of
10,240 rows. The regions keep the Hilbert order. They are 110 rows in one
row group, so every read fetches the whole file.

In the centerlines, the `rgi_id` order is also the `rgi_g_id` order. The
lines of one glacier are consecutive, so a filter on `rgi_g_id` selects one
row group, or two at a boundary. The intersect IDs do not follow the glacier
IDs as closely.

`scripts/measure_lookups.py --product NAME` reads each file by the key of
its README example. The sample is one random row of each first-order region,
and Grosser Aletsch Gletscher for the centerlines and the intersects. MB
fetched, median / maximum:

| Product | Key | Reader | Before | After |
| --- | --- | --- | ---: | ---: |
| complexes | `rgi_id` | geopandas | 99.3 / 152.2 | 5.3 / 22.5 |
| complexes | `rgi_id` | DuckDB | 11.3 / 26.5 | 4.2 / 12.4 |
| complexes | `rgi_id` and bbox | geopandas | 36.7 / 60.8 | 14.3 / 22.6 |
| centerlines | `rgi_g_id` | geopandas | 56.6 / 127.8 | 7.7 / 8.1 |
| centerlines | `rgi_g_id` | DuckDB | 30.9 / 72.9 | 2.9 / 3.3 |
| centerlines | `rgi_g_id` and bbox | geopandas | 23.1 / 40.2 | 7.8 / 8.2 |
| intersects | `rgi_g_id_1` or `rgi_g_id_2` | geopandas | 14.1 / 18.1 | 6.5 / 7.1 |
| intersects | `rgi_g_id_1` or `rgi_g_id_2` | DuckDB | 14.1 / 14.1 | 14.0 / 14.0 |
| intersects | either key and bbox | DuckDB | 1.6 / 2.2 | 1.8 / 2.3 |

DuckDB 1.5.6 does not skip row groups on an `OR` across two columns. It
reads the whole intersects file for the README lookup in both orders. A bbox
filter lets it skip row groups.

| Product | Row groups before | Row groups after | MB before | MB after |
| --- | ---: | ---: | ---: | ---: |
| complexes | 18 | 48 | 213.3 | 214.7 |
| centerlines | 36 | 90 | 211.0 | 210.3 |
| intersects | 13 | 13 | 17.0 | 16.8 |

`rashid check --data` finds no PTL-DAT-006 error on any of the files. The
schema and the rows of each file equal those of its Hilbert version.

## The other products (measured 2026-10-23)

`convert` builds all five files in 12 min 5 s and peaks at 5.8 GB of memory.

| Collection | Rows | File |
| --- | ---: | ---: |
| glaciers | 274,531 | 258.0 MB |
| complexes | 192,869 | 213.3 MB |
| centerlines | 367,724 | 211.0 MB |
| intersects | 130,429 | 17.0 MB |
| regions | 110 | 1.0 MB |

- **Typing.** The I table's `length_m` is a float and the L table's is an
  integer, so the centerline dtypes are a table of their own
  (`dtypes.CENTERLINE_DTYPES`). The I table keeps float64.
- **Fixes.** The text repair, the Z drop and the validity repair run on every
  product (`assemble._apply_fixes`). 7 complex outlines are invalid and are
  repaired. All glacier outlines are valid under the GEOS in the environment.
- **Links.** Each of the 274,531 glaciers is in exactly one complex. Each
  has exactly one main centerline, and its `length_m` equals the glacier's
  `lmax_m`. Each intersect and each centerline refers to a glacier in the glaciers
  file.
- **Regions.** The summary CSVs contain only the codes and names of the
  shapefiles, and no statistics. The build uses them as a witness and fails
  when they differ. The file stacks both levels with a `level` column.
  RGI splits regions 10 and 19-15 at the antimeridian into two polygons.
  The file joins each pair into one MultiPolygon row, so a region code names
  one row: 20 rows of level 1 and 90 of level 2.
- **Region labels.** The regions have no label point. The tiles use the
  `point_on_surface` of each region's largest polygon. The label points are
  not a column of the GeoParquet file.
- **Region boundaries.** Neighbouring polygons store a shared border once
  each, and a dash pattern drawn twice looks solid. The `region-boundaries`
  layer stores each border once (`tiles.write_region_boundaries`). Its only
  column is `level`: 1 where the line bounds a first-order region, else 2.
  Neighbours often split a border at different vertices, so the outlines are
  snapped to a grid of 1e-5 degrees (about 1.1 m) and noded. The grid is
  finer than a z12 tile resolves. The outline that closes regions 10, 19,
  19-15, 20 and 20-01 at the antimeridian is not a border and is left out.
  The outline of region 19 along the South Pole is left out for the same
  reason. Web Mercator cannot show it.
  The border of 10-05 and 10-06 at the antimeridian is kept at 180 only.
  Contiguous lines of one level are merged into one LineString. The 110
  polygons give 418 lines: 66 of level 1 and 352 of level 2.
- **Regions license.** The regions are GTN-G's. Their DataCite record states
  "Open access for scientific and educational purposes under requirement of
  correct citation", not CC-BY-4.0. The collection declares `license: other`
  with a link to the GTN-G page. The author decides this before publishing.

## Web-map archive

`src/rgi_catalog/tiles.py` builds `v7.0/rgi7.0.pmtiles` from the staged
glaciers file. Every collection of the version draws from this one archive.
Each lists it as a `visual` asset and a `rel: pmtiles` link at
`../rgi7.0.pmtiles`. The tiler is tylertoo 0.8.0.

### The tylertoo binary

The PyPI wheel of tylertoo 0.8.0 has only the Python API. That API writes one
layer per archive and has no `pyramid`, `--entry-zoom` or
`--include-property`. The build uses the release binary instead
(`tylertoo-0.8.0-x86_64-unknown-linux-musl.tar.gz`). The constant `TYLERTOO` in
`src/rgi_catalog/tiles.py` pins it by sha256, and `sources.fetch` verifies it into `.cache/`.

The 0.8.0 binary lacks two flags that the online documentation lists:
`--size-valve` and `--name`/`--attribution`/`--description` on `tiles` and
`pyramid`. The build writes the archive metadata itself
(`tiles.set_metadata`). It copies the header, directories and tile data byte
for byte and replaces only the metadata block.

### The archive build

1. `write_labels` writes one point per glacier with a `display_name`, at
   RGI's own `cenlon`/`cenlat`, to `staging/v7.0/.tiles/labels.parquet`.
2. `write_early_lines` writes the centerlines and the intersects that enter
   before z9, with their `line_minzoom`.
3. `write_web_mercator` writes each band's input in Web Mercator.
4. `tylertoo tiles` builds each zoom band of each layer into its own archive.
5. `tylertoo pyramid --band LO-HI:ARCHIVE:LAYER …` joins the bands. Bands of
   different layers may share zooms. Each band's label must equal its layer
   name, or `pyramid` refuses the build.

| Layer | Band | Settings |
| --- | --- | --- |
| `glaciers` | z0, …, z9, one band each | `--no-density-drop --polygon-thinning 0 --polygon-visibility 0 --sort-key area_km2`, tiled to z+1 |
| `glaciers` | z10–12 | `--no-density-drop --polygon-thinning 0 --polygon-visibility 0 --simplify-factor 0.5` |
| `glacier-labels` | z7–12 | `--entry-zoom label_minzoom:7=7,…,12=12 --no-density-drop` |
| `regions` | z0–12 | `--no-density-drop --polygon-thinning 0 --polygon-visibility 0` |
| `region-boundaries` | z0–12 | as `intersects` |
| `region-labels` | z0–12 | `--no-density-drop --point-thinning 0` |
| `complexes` | z0, …, z9, z10–12 | as `glaciers` |
| `centerlines` | z4–7 (early lines), z8 (early lines), z9, z10–12 | `--no-density-drop --line-thinning 0 --line-visibility 0 --no-coalesce-lines --simplify-factor 0.5`, and `--entry-zoom line_minzoom:4=4,…,7=7 --filter "line_minzoom < 8"` at z4–7 |
| `intersects` | z4–8 (early lines), z9–12 | as `centerlines`, with `--simplify-factor 0`, and `--entry-zoom line_minzoom:4=4,…,8=8` at z4–8 |

Every band from z10 is complete, and so are the region bands, the
centerline and intersects bands from z9, and the early-line bands except
the z8 centerlines.

- **Line coalescing** joins touching segments into one feature with the
  attributes of one of them. It is on by default. With it on, z10 kept
  127,439 of 130,429 intersects and z8 lost 4,116 centerlines.
- **Band edges.** A band of z9–12 lost one centerline at z9. A band of z9
  alone kept all 367,724.
- **Simplification** at half a GSD still collapsed short divides: z10 kept
  127,730 intersects. With `--simplify-factor 0` it keeps all of them. At
  the default factor z0 kept 261 of 419 region boundaries.

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
- The finest zoom of a tiling keeps every source feature, whatever its
  entry zoom. Without a filter the z4–7 centerline band kept all 286,376
  early lines at z7 instead of 9,579, and 27 z7 tiles exceeded the size
  limit. `--filter "line_minzoom < 8"` keeps the lines that enter at z8 out.

### Simplification at high latitudes

tylertoo 0.8.0 simplifies lon/lat input with its tolerance in degrees. On
the map a degree of latitude is 1/cos(lat) times as long as a degree of
longitude. So at 78°N the tolerance is five times too large in the
north-south direction. On Barents Island (Svalbard) the overview outlines
moved up to 2.5 pixels at z7–9 and 1.2 pixels at z10, instead of 0.5 and
0.25. The outlines looked jagged one zoom before the full outline arrived.

The same glaciers as Web Mercator input moved at most 0.55 pixels at z9 and
kept 5,155 instead of 3,434 vertices. So `tiles.write_web_mercator`
gives the tiler each band's input in EPSG:3857. Web Mercator ends at
85.05°. The region polygons reach 90°S, and the input cuts them off there.
The extents of the other products are within 84° of the equator.

A tiling does not simplify its finest zoom, so a unit test pads its band.

The overview points are thinned on a grid of 4 GSD. In map units that grid
is square, so high latitudes keep more points than before. The z0 tile grew
from 101 KB to 190 KB, and the archive from 1,066.6 MB to 1,098.8 MB.

At its first outline zoom a sliver narrower than half a pixel collapses
under simplification and is absent at that zoom: 55 of 82,272 glaciers at
z7. The degree tolerance collapsed at least as many.

### Line entry zooms

Before, the main centerlines entered at z8 and every other line at z9. An
ice cap then showed its outline for several zooms before its centerlines
and divides. `tiles.write_early_lines` gives each line the first zoom from
z4 at which its Web Mercator bounding box spans 32 pixels (`line_minzoom`).
A main centerline enters at z8 at the latest and every other line at z9.
On Barents Island the main centerlines enter at z6–7 and the long divides
at z7–8. The z8 band keeps 282,123 of the 286,376 early centerlines. Its
oversized tiles drop the rest, which enter at z9.

Lines that span 32 pixels, worldwide:

| z | 4 | 5 | 6 | 7 | 8 |
| --- | ---: | ---: | ---: | ---: | ---: |
| centerlines | 159 | 881 | 3,399 | 9,579 | 22,337 |
| intersects | 22 | 196 | 815 | 2,342 | 5,418 |

### Zoom range

The first build went to z14 and was 2.4 GB. z14 alone was 2.2 million tiles,
mostly about 1 KB each: tiles inside ice caps that contain one clipped polygon
and its 39 properties. A z12 tile resolves about 2.4 m at the equator, finer
than the imagery behind the outlines, and clients overzoom above it. So the archive
ends at z12 for each layer, because a client overzooms one source as a
whole.

Leaving the four long submission text columns out of the tiles saves 12% of
the z10–12 band (550 to 485 MB). The tiles keep every scalar column.

The glaciers layer starts at z0, so the default style shows data at the full
extent. z9 keeps all 274,531 glaciers.

### Low zooms

With tylertoo defaults z0 held 117 of 274,531 glaciers. Polygons
smaller than 2 GSD fail the visibility gate, and the density budget thins the
rest. The
Alps and High Mountain Asia were almost empty at world scale.

Below z10 the glaciers and the complexes are an overview built per zoom
(`tiles.write_overview`). At each zoom a feature that spans 3 pixels of a
512-pixel tile is its outline. A smaller feature is RGI's point (`cenlon`,
`cenlat`). So large glaciers keep their shape at low zooms, as in
Google Earth Engine, and a small one is a dot. The points keep one per grid
cell of 4 GSD, about a pixel, and each cell keeps the point of the largest feature
(`--sort-key area_km2`). The density limit thins only the points.

Each zoom is its own band. The finest zoom of a tiling keeps every source
feature, so each band is tiled one zoom further (`pad_zoom`) and `pyramid`
keeps only its own zoom. A glacier at the antimeridian is a MultiPoint where
the tile buffer wraps.

Features drawn as outlines, of 274,531 glaciers and 192,869 complexes:

| z | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| glaciers | 82 | 435 | 1,455 | 3,652 | 8,210 | 17,622 | 38,217 | 82,272 | 151,747 | 220,684 |
| complexes | 76 | 201 | 516 | 1,105 | 2,707 | 7,235 | 18,837 | 45,432 | 90,798 | 143,633 |

The earlier overview drew every glacier as a point up to z6 and a small one
as a square at z7–8. Large glaciers then appeared all at once at z7.

### Result (measured 2026-10-24)

`tiles --version 7.0` takes 12 min 21 s and peaks at 6.1 GB of memory. The
per-zoom overview inputs take most of the time. The archive is 1,043.8 MB
with every layer.

The region polygons cover the oceans and the Antarctic, so z12 addresses
11.9 million tiles. Most are the same small tile inside a region. "MB
addressed" counts each addressed tile, so it repeats the shared ones.

The overview bands (z0–9) of the glaciers and the complexes contain only the
key and the columns the styles read (`tiles.GLACIER_OVERVIEW_COLUMNS`,
`tiles.COMPLEX_OVERVIEW_COLUMNS`). Every column is in the tiles from z10.
The largest tiles cover High Mountain Asia.

| z | Tiles | MB addressed | p50 bytes | Max bytes |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 0.1 | 101,396 | 101,396 |
| 1 | 4 | 0.2 | 31,907 | 121,118 |
| 2 | 16 | 0.7 | 18,011 | 222,867 |
| 3 | 64 | 1.8 | 3,482 | 223,225 |
| 4 | 225 | 3.8 | 806 | 399,597 |
| 5 | 832 | 7.4 | 233 | 445,550 |
| 6 | 3,100 | 13.5 | 197 | 496,761 |
| 7 | 12,106 | 23.0 | 193 | 479,630 |
| 8 | 47,447 | 52.6 | 192 | 402,905 |
| 9 | 187,891 | 106.4 | 192 | 206,014 |
| 10 | 748,229 | 298.1 | 192 | 156,538 |
| 11 | 2,983,757 | 782.0 | 192 | 87,217 |
| 12 | 11,916,787 | 2667.4 | 192 | 61,220 |

Decoded counts: 274,531 glaciers at z10, z11 and z12. Labels: 244 at z7,
714 at z8, 1,462 at z9, 2,715 at z10, 4,514 at z11 and all 9,457 at z12.
Each equals the number of named glaciers whose `label_minzoom` has been
reached.

`label_minzoom` falls by one zoom for every factor of 4 in area, because
each zoom step quadruples a glacier's area on screen. A glacier of 1 km²
gets its label at z11. The result is clamped to z7–z12.

## Glacier styles

The author approved this style plan on 2026-10-22. `styles.glacier_styles`
builds the styles of the glaciers collection.

| Style | Column | Expression | Legend |
| --- | --- | --- | --- |
| `glaciers` (default) | none | outlines and names | no |
| `median-elevation` | `zmed_m` | `step` at 1,000 m to 5,000 m | 6 classes |
| `surge-evidence` | `surge_type` | `match` on 0 to 3 | 4 classes |
| `terminus-type` | `term_type` | `match` on 1 and 9 | 2 classes |
| `same-as-rgi6` | `is_rgi6` | `match` on the flag | 2 classes |

Every style draws the region boundaries under its data and the region names
over it. Each name is under its number (`11`, `11-01`). The boundaries
come from the `region-boundaries` layer, which stores each border once, so
the dash patterns stay in step. A first-order boundary is a long dash
(`[5, 2.5]` line widths, 1.2 px, `#757575`) and shows from z0. A
second-order boundary is a short dash (`[2.5, 2.5]`, 0.8 px, `#9e9e9e`) and
shows from z3.

The styles draw the names on top. The glyphs come from OpenFreeMap. A
region name is in Noto Sans Bold or Noto Sans Regular. A glacier name
follows the label line of its glacier in the `glacier-labels` layer. It
uses Noto Sans Italic at 14 px with a letter spacing of 0.2 em, placed at
the line center. The `tiles` step fits each label line to that text with
the glyph advances in `metadata/glyph_advances.yaml`. A glacier without a
label line has no name in the styles.

A main centerline runs from the head to the terminus. Its last vertex is
RGI's terminus point (`termlon`, `termlat`) for each of the 9,457 named
glaciers with a main centerline. The `tiles` step puts the label line near
the terminus, as swisstopo's national map writes a name along the tongue.
At each zoom, a stretch of the smoothed centerline slides up from the
terminus in steps of 2 px. The first stretch that passes two checks wins.
MapLibre must keep the name. The text must also keep 11.6 px to the
glacier's own outline on both sides of the line. That is half the text
height (0.6 em), the 1.2 px halo and a margin of 2 px. A narrow tongue thus
pushes the name up the glacier, or drops the line at that zoom. The downstream end of the name keeps a tenth of the centerline, and
at least 8.4 px, to the terminus. The middle of the centerline is always a
candidate. A glacier has a label line for each zoom from its `line_zoom` to
z12, with that zoom in `label_zoom`. The `glacier-labels` layer has one
band per zoom, so a tile holds only the lines of its own zoom. The styles
draw the line whose `label_zoom` is the map zoom, capped at z12. So a name
moves down the glacier at each whole zoom.

The browser labels a legend entry with the `match` branch value. So each
`match` takes a nested expression that turns the code into the
user guide's label, and branches on that label. The legend reads "Observed",
not "3".

RGI 7.0 assigns only the marine-terminating terminus class (1,561
glaciers). Every other glacier is "not assigned" (9). The user guide states
that no lake- or shelf-terminating class is available. So the terminus style
has two classes.

`tests/unit/test_styles.py::test_match_branches_exist_in_data` checks each
`match` against the staged file when it exists. Measured counts:

| Column | Values |
| --- | --- |
| `surge_type` | 0: 271,901, 1: 630, 2: 825, 3: 1,175 |
| `term_type` | 1: 1,561, 9: 272,970 |
| `is_rgi6` | true: 73,797, false: 200,734 |
| `zmed_m` | <1,000: 38,275, 1–2k: 66,180, 2–3k: 20,622, 3–4k: 22,258, 4–5k: 45,150, ≥5k: 82,046 |

The colours changed on 2026-10-24, because the pastel fills were hard to see
on grey basemaps. Each product has one colour in every style. The
centerlines and intersects styles draw the glaciers in the glacier colours,
but faint, so the lines are the subject. The colours are in `styles.py`. Each product colour clears 3:1 against
a light grey basemap, and the products stay apart for colour-blind readers.

The outline of every style is a `line` layer from z0, about one pixel wide
at low zooms. At world scale a glacier is smaller than a pixel, so a fill
alone draws nothing there. A `circle` layer filtered to points draws the
overview points, 1.5 to 2.5 px wide, in the fill colour. Themed styles colour
the outline and the dots with the theme's expression, and the legend still
comes from the fill.

The `same-as-rgi6` style follows the map in the RGI 7.0 user guide.

## Local preview

`preview --version 7.0` links `catalog/` and `staging/` into one tree at
`.cache/preview` and serves it on port 8000 with Range and CORS. The tree is
outside `staging/`, because `tools/upload_data.py` walks `staging/` and would
upload the symlinked data a second time. Dot paths in `staging/` (`.reports`,
`.tiles`) stay out of the preview, as they stay out of the upload.

`RGI_QUERY_BASE=http://localhost:8000 pixi run pytest
tests/unit/test_documented_queries.py` runs every SQL recipe of the published
READMEs and AGENTS files against the preview.

chiitiler renders the style checks and the thumbnails. Its prebuilt
MapLibre Native binary exists for Node 24, not for Node 26, and it links ICU
74 and `libOpenGL.so.0`. conda-forge has no ICU 74. So chiitiler runs
from its Docker image (`ghcr.io/kanahiro/chiitiler`, digest
`sha256:d3586159af69…`), with the repository bind-mounted read-only at its
own path:

```bash
docker run -d --rm --name rgi-chiitiler -p 13579:3000 -e CHIITILER_PROCESSES=0 \
  --mount "type=bind,source=$PWD,target=$PWD,readonly" ghcr.io/kanahiro/chiitiler:latest
```

A `/clip` bbox may run past 180°. The world thumbnails span 169°W to 191°E,
once around the world from the border between Alaska and North Asia. No
region box is cut at the image edges. The region boundaries leave out the
edge that closes North Asia at 180°, so the boundary does not cross it.

## Thumbnails (rendered 2026-10-24 and 2026-10-30)

Each collection, the root catalog and the version catalog have a 1024 px
WebP thumbnail (quality 85). The images live in `metadata/thumbnails/` at the
path of their document. `render` copies each one next to its document and
registers it. A collection lists it as an asset with the `thumbnail` role. A
catalog carries no assets (PTL-AST-005), so a catalog lists it as a
`rel: preview` link, which the browser reads when a document has no assets.

`scripts/thumbnails.sh` renders them with chiitiler.
`scripts/thumbnail_style.py` points the published default style at the local
archive and drops its symbol layers. The thumbnails need no credit:

- The root, the version and the regions are world views over the land of
  Natural Earth (`scripts/naturalearth_land.py`, 1:50m, public domain).
- The glaciers, complexes, intersects and centerlines share one frame on
  white: the Garibaldi and Marinelli glaciers, Cordillera Darwin, just above
  map zoom 10.

| Image | Style | bbox |
| --- | --- | --- |
| root, `v7.0` | Glaciers | -169,-62.15,191,83 |
| regions | Glacier regions | -169,-62.15,191,83 |
| glaciers, complexes, intersects, centerlines | each default | -70.078019,-54.786293,-69.421981,-54.533313 |

The world views were rendered again on 2026-10-30 for the dashed region
boundaries, with the image at digest `sha256:e1e2f6b3c9c1…`. The new
renders of the glacier frame differed from the old ones in at most 8 pixels,
so the old images stay.

The frame holds 232 intersects, ten times the divide length of a frame of the
Baltoro glacier at map zoom 11. At exactly map zoom 10 chiitiler draws the
z9 tiles, which hold the glacier overview, so the frame is at zoom 10.1.

chiitiler can answer `/clip` before every tile has loaded. A long-running
server also dropped a whole layer from a render. The script therefore
repeats each request until two images are byte-identical, on a freshly
started server.
