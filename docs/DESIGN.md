# Design decisions

This file records the measured decisions behind the build. The design itself
is in `docs/superpowers/specs/2026-10-22-rgi-mirror-design.md`.

## The catalog is generated

The template expects a hand-edited `catalog/`. This repository generates it.
`pixi run python -m rgi_catalog render` writes `catalog/` from the tracked
files in `metadata/`. A unit test fails when `catalog/` differs from a fresh
render. Edit `metadata/`, never `catalog/`.

`render --version 7.0` first measures the staged files into
`metadata/builds/v7.0.json`: sizes, checksums, extents, row counts, schemas,
the archive's layers, and RGI's `attributes_metadata.json` of each product
used. The record keeps its `updated` time when nothing else changed, so a
second render changes nothing. `render --no-record` renders from the
committed record alone, which is how CI and the drift test run.

The data lives in `staging/`, not beside `catalog/`. The `gates` task
therefore sets `CI_LIGHT=1` as CI does, and `tests/test_links.py` exempts
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

## The other products (measured 2026-10-23)

`convert` builds all five files in 12 min 5 s and peaks at 5.8 GB of memory.

| Collection | Rows | File |
| --- | ---: | ---: |
| glaciers | 274,531 | 258.0 MB |
| complexes | 192,869 | 213.3 MB |
| centerlines | 367,724 | 211.0 MB |
| intersects | 130,429 | 17.0 MB |
| regions | 112 | 1.0 MB |

- **Typing.** The I table's `length_m` is a float and the L table's is an
  integer, so the centerline dtypes are a table of their own
  (`dtypes.CENTERLINE_DTYPES`). The I table keeps float64.
- **Fixes.** The text repair, the Z drop and the validity repair run on every
  product (`assemble._apply_fixes`). 7 complex outlines are invalid and are
  repaired. No glacier outline is invalid under the GEOS in the environment.
- **Links.** Each of the 274,531 glaciers is in exactly one complex. Each
  has exactly one main centerline, and its `length_m` equals the glacier's
  `lmax_m`. Every intersect and centerline names a glacier that exists.
- **Regions.** The summary CSVs hold only the codes and names of the
  shapefiles, and no statistics. The build uses them as a witness and fails
  when they differ. The file stacks both levels with a `level` column.
- **Region labels.** The regions have no label point. The tiles use the
  `point_on_surface` of each region's largest polygon. The label points are
  not a column of the GeoParquet file.
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
| `glaciers` | z0–9 | `--representation 0-6:point,7-8:square --no-density-drop --sort-key area_km2` |
| `glaciers` | z10–12 | `--no-density-drop --polygon-thinning 0 --polygon-visibility 0 --simplify-factor 0.5` |
| `glacier-labels` | z7–12 | `--entry-zoom label_minzoom:7=7,…,12=12 --no-density-drop` |
| `regions` | z0–12 | `--no-density-drop --polygon-thinning 0 --polygon-visibility 0` |
| `region-labels` | z0–12 | `--no-density-drop --point-thinning 0` |
| `complexes` | z0–9, z10–12 | as `glaciers` |
| `centerlines` | z8–9, z10–12 | `--no-density-drop --line-thinning 0 --line-visibility 0 --no-coalesce-lines --simplify-factor 0.5` |
| `intersects` | z10–12 | as `centerlines`, with `--simplify-factor 0` |

Every band from z10 is complete, and so are the region bands.

- **Line coalescing** joins touching segments into one feature with the
  attributes of one of them. It is on by default. With it on, z10 kept
  127,439 of 130,429 intersects and z8 lost 4,116 centerlines.
- **Simplification** at half a GSD still collapsed short divides: z10 kept
  127,730 intersects. With `--simplify-factor 0` it keeps all of them.

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
extent. z9 keeps all 274,531 glaciers.

### Low zooms

With tylertoo defaults z0 held 117 of 274,531 glaciers. The visibility gate
drops polygons smaller than 2 GSD, and the density budget thins the rest. The
Alps and High Mountain Asia were almost empty at world scale.

Up to z6 each glacier is now a point. Points skip the visibility gate and
keep one per point-grid cell of 4 GSD, about one screen pixel. The largest
glacier (`--sort-key area_km2`) wins each cell and gives the cell its
attributes. Without the density budget every occupied cell keeps a point:
z0 holds 1,310 points and z4 39,989. At z7–8 a polygon too small for the
zoom is a placeholder square. The finest zoom of a band keeps the source
geometry, so the squares stop at z8. A glacier at the antimeridian is a
MultiPoint at z0, where the tile buffer wraps.

`--collapse-square` alone kept polygons and gave z0 1,017 squares of about
a quarter pixel. Only their outlines showed. tippecanoe's tiny-polygon
reduction gives a similar result. The newer tylertoo documentation describes
area-accumulated squares as the default, but 0.8.0 does not have them.

### Result (measured 2026-10-23)

`tiles --version 7.0` takes 6 min 13 s and peaks at 4.4 GB of memory. The
archive is 1,242.8 MB with every layer. The glaciers-only archive was
805.4 MB, and 759.0 MB before the points and squares.

The region polygons cover the oceans and the Antarctic, so z12 addresses
11.9 million tiles. Most are the same small tile inside a region. The
archive stores 425,392 distinct tiles, and its directories are 4.2 MB. "MB
addressed" counts each addressed tile, so it repeats the shared ones.

The z0 tile is 314 KB. Its glacier and complex points carry every scalar
column of the largest feature of each grid cell.

| z | Tiles | MB addressed | p50 bytes | Max bytes |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 0.3 | 313,720 | 313,720 |
| 1 | 4 | 0.7 | 174,944 | 329,677 |
| 2 | 16 | 1.7 | 53,134 | 359,727 |
| 3 | 64 | 4.1 | 10,804 | 381,292 |
| 4 | 225 | 7.8 | 1,198 | 485,586 |
| 5 | 832 | 15.0 | 233 | 480,988 |
| 6 | 3,100 | 26.2 | 197 | 479,794 |
| 7 | 12,106 | 49.7 | 193 | 583,718 |
| 8 | 47,447 | 96.9 | 192 | 588,053 |
| 9 | 187,891 | 205.3 | 192 | 471,843 |
| 10 | 748,229 | 298.1 | 192 | 156,538 |
| 11 | 2,983,757 | 782.0 | 192 | 87,217 |
| 12 | 11,916,787 | 2667.4 | 192 | 61,220 |

Decoded counts: 274,531 glaciers at z10, z11 and z12. Labels: 244 at z7,
714 at z8, 1,462 at z9, 2,715 at z10, 4,514 at z11 and all 9,467 at z12.
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
| `full-map` (default) | none | blue fill and outline, names | no |
| `median-elevation` | `zmed_m` | `step` at 1,000 m to 5,000 m | 6 classes |
| `surge-evidence` | `surge_type` | `match` on 0 to 3 | 4 classes |
| `terminus-type` | `term_type` | `match` on 1 and 9 | 2 classes |
| `same-as-rgi6` | `is_rgi6` | `match` on the flag | 2 classes |

Every style draws the names on top. The names use CARTO's glyphs, which the
browser's default basemaps also use, in Open Sans Italic.

The browser labels a legend entry with the `match` branch value. Each
`match` therefore takes a nested expression that turns the code into the
user guide's label, and branches on that label. The legend reads "Observed",
not "3".

RGI 7.0 assigns only the marine-terminating terminus class (1,561
glaciers). Every other glacier is "not assigned" (9). The user guide states
that no lake- or shelf-terminating class is available. The terminus style
therefore has two classes.

`tests/unit/test_styles.py::test_match_branches_exist_in_data` checks each
`match` against the staged file when it exists. Measured counts:

| Column | Values |
| --- | --- |
| `surge_type` | 0: 271,901, 1: 630, 2: 825, 3: 1,175 |
| `term_type` | 1: 1,561, 9: 272,970 |
| `is_rgi6` | true: 73,797, false: 200,734 |
| `zmed_m` | <1,000: 38,275, 1–2k: 66,180, 2–3k: 20,622, 3–4k: 22,258, 4–5k: 45,150, ≥5k: 82,046 |

The author asked for centerlines in red over the blue outlines in the full
map. The centerlines layer comes with the centerlines product.

The outline of every style is a `line` layer from z0, about one pixel wide
at low zooms. At world scale a glacier is smaller than a pixel, so a fill
alone draws nothing there. A `circle` layer filtered to points draws the
z0–6 points, 1.5 to 2.5 px wide. Themed styles colour the outline and the
dots with the theme's expression, and the legend still comes from the fill.

The `same-as-rgi6` style follows the map in the RGI 7.0 user guide: "Same as
RGI 6.0" in blue and "New in RGI 7.0" in red.

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
74 and `libOpenGL.so.0`. conda-forge has no ICU 74. chiitiler therefore runs
from its Docker image (`ghcr.io/kanahiro/chiitiler`, digest
`sha256:d3586159af69…`), with the repository bind-mounted read-only at its
own path:

```bash
docker run -d --rm --name rgi-chiitiler -p 13579:3000 -e CHIITILER_PROCESSES=0 \
  --mount "type=bind,source=$PWD,target=$PWD,readonly" ghcr.io/kanahiro/chiitiler:latest
```

A `/clip` bbox that spans the full ±180° renders only part of the data. Frame
world views at ±170° or less.
