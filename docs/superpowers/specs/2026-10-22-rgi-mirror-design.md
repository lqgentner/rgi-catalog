# RGI cloud-native mirror — design

Date: 2026-10-22. Author: Luis Gentner, with Claude. Status: for the author's
approval.

## 1. Intent

The Randolph Glacier Inventory (RGI) is the standard global glacier inventory.
Version 7.0 ships as nested zips of per-region shapefiles plus CSV and JSON side
tables, behind an Earthdata login at NSIDC. That works for downloading a region
into a desktop GIS. It does not work for the things cloud-native formats make
easy: querying one glacier out of a remote file without downloading it, joining
attributes in DuckDB, or dropping the whole inventory into a web map.

This repository builds a **mirror** of RGI 7.0 on Source Cooperative:

- **GeoParquet** files that a reader can query over HTTP, and
- **one vector PMTiles archive** that a web map can display directly, with
  glacier names at zoom-dependent levels, much as the OpenStreetMap PMTiles do,
- described by a **Portolan/STAC catalog** that can be browsed in the Portolan
  data browser.

**Why now.** Cloud-native geospatial is little known in glaciology. This is a
proof of concept on the author's personal Source Cooperative account
(`lqgentner`). The author will show it, together with a small MapLibre viewer
(a later project), to the RGI consortium, and pitch making a cloud-native
distribution official with 7.0 or the upcoming 7.1. The consortium is
preparing RGI 7.1 (empty `GLIMS-RGI/rgi71_scripts` repo, `v7.1/` user-guide
scaffold). By its stated policy 7.1 changes attributes and format, not
outlines. Its fixes target several of the defects listed in §5.3.

**Success looks like:** a glaciologist pastes one DuckDB query from the README
and gets the Rhone glacier with its hypsometry, without downloading anything;
the Portolan browser opens every collection with a readable map; the RGI people
see a catalog that credits them as the producer and changes none of their
values.

## 2. Goals, non-goals, anti-goals

**Goals**

- Mirror every RGI 7.0 product: glaciers (G), complexes (C), centerlines (L),
  intersects (I), and the region outlines.
- Restructure freely: gather information scattered across shapefiles, CSVs and
  JSON link files into a few self-contained files (§5).
- Fix known upstream errors, each one documented (§5.3).
- One PMTiles archive per RGI version, holding all products as layers, with
  name labels. The tiles carry the same attributes as the Parquet files.
- Pass rashid (the Portolan validator) and follow the GeoParquet distribution
  best practices.
- A local preview (local server, local Portolan browser, rashid) before
  anything is uploaded.
- Support later RGI versions (7.1, 8.0) as siblings without restructuring.

**Non-goals (this project)**

- The MapLibre viewer with glacier search. It comes later, possibly on GitHub
  Pages. This design only keeps the files friendly to it (§5.5).
- RGI 6.
- Scheduled or CI-driven builds. RGI changes every few years; the build runs
  locally.
- Dated releases, `versions.json`, `portolan push`.
- Spatial partitioning (every file is well below the ~2 GB threshold).
- Registering the catalog in the Portolan registry. That waits for the outcome
  of the pitch.

**Anti-goals: a failure even if it works**

- A value in the mirror that differs from RGI without a documented fix.
  Restructuring is allowed. Changing values is not, apart from the fixes
  in §5.3.
- A map that shows something the Parquet files do not contain.
- Anything that reads as if the author produced RGI, or as if the mirror were
  official. The RGI Consortium is the producer and the citation is RGI's.
- Changed or re-minted IDs. `rgi_id` stays the authoritative key.

## 3. Constraints and decided facts

These were decided with the author, or are fixed by RGI or the spec.

- **Host:** the `lqgentner` Source Cooperative account, through the S3 proxy
  `https://data.source.coop` with the `source-coop` named profile (the same
  setup as the author's `glace-catalog`). Product slug: `rgi` *(Claude's
  call: confirm the product exists on source.coop before the first upload)*.
- **Visibility (decided):**
  - The Source Cooperative product is **public but unlisted**: readable by
    anyone with the URL, not advertised.
  - The GitHub repository `lqgentner/rgi-catalog` is **private** until the
    first upload. It goes public when the link is shared with the RGI people.
- **Not endorsed (decided):** every README, and the root and collection
  descriptions, state that this is an **unofficial mirror, not endorsed by
  the RGI Consortium**, and that citation and credit belong to RGI (§7.2).
- **RGI 7.0 first.** Other versions are later siblings.
- **Versioning (decided):**
  - Each RGI version is its own sub-catalog with its own collections:
    `v7.0/`, later `v7.1/`. Versions are separate datasets (IDs embed the
    version: `RGI2000-v7.0-G-11-00001`), never merged.
  - Within one RGI version there are **no dated releases**. A fix to the
    conversion or the catalog overwrites the files at the same paths. The
    URLs stay stable because people hard-code them in DuckDB queries and web
    maps.
  - Each such fix is a **mirror revision**. It is recorded in the collection's
    `version` field (STAC version extension, which PORTO-CORE-008 requires for
    dataset versioning), in `updated`, in `file:checksum`, in the Parquet file
    metadata, in a git tag and in `CHANGELOG.md`. Old revisions are not
    stored. The build is reproducible from a tag plus the pinned upstream
    checksums.
  - *Claude's call:* the version string is `7.0-r1`, `7.0-r2`, …, and the git
    tag carries the same name.
  - A breaking schema change within a version (renaming or removing a queried
    column) is out of scope. Prefer adding columns. Decide if it ever happens.
- **Data policy (decided):** restructuring is allowed, and fixing documented
  upstream errors is allowed. Values never change otherwise. A cleaned
  `display_name` is allowed because `rgi_id` stays authoritative and nobody
  searches by name reliably.
- **Parquet and PMTiles hold the same data (decided).** Every attribute shown
  on the map exists in the Parquet. Exceptions are only what vector tiles
  cannot store (§6.2).
- **One PMTiles archive per RGI version (decided)**, with several layers, not
  one archive per product.
- **The corrected RGI6 links come from Fabien Maussion's server (decided).**
- **Tooling:** pixi (conda-forge + PyPI), Python 3.13. tippecanoe comes from
  conda-forge.
- **Portolan:** follow the `portolan` skills (installed plugin v0.5.0,
  checked up to date on 2026-10-22), especially `git-backed-catalog`,
  `portolan-bootstrap`, `sourcecoop`, `portolan-thumbnails` and
  `reading-portolan`. The spec is ground truth and rashid implements it.
- **GeoParquet:** follow
  [Distributing GeoParquet](https://github.com/opengeospatial/geoparquet/blob/main/format-specs/distributing-geoparquet.md)
  (read 2026-10-22).
- **Glossary.** "Mirror" in this document means the mirror of RGI. The
  Portolan "item mirror" (`items.parquet`) is not used: there are no items.

## 4. Upstream source

### 4.1 What RGI 7.0 contains

Facts from inspecting the release (2026-10-22). They are the builder's
starting point.

| Product | Features | Geometry | Global zip |
| --- | --- | --- | --- |
| G glaciers | 274,531 | Polygon Z (Z=0), holes, no multipolygons | 464 MiB |
| C complexes | 192,869 | Polygon Z (Z=0) | 371 MiB |
| L centerlines | 367,724 | LineString | 237 MiB |
| I intersects | 130,429 | LineString Z (Z=0) | 28 MiB |
| regions | 21 o1 + 91 o2 polygons | Polygon | 2.2 MiB |

Other facts about the release:

- The CRS is EPSG:4326.
- The glacier outlines hold 38 M vertices; the largest polygon has 151 k.
- Each global zip nests one zip per first-order region (01–19). Region 20,
  the Antarctic mainland, has no glaciers.
- **Per-region side files:**
  - `-attributes.csv`, the same attributes as the `.dbf`.
  - `-attributes_metadata.json`, per column: `long_name`, `description`,
    `datatype`, `units`, `source`, `rgi6_name`. Every product has one.
  - G only: `-hypsometry.csv` (`rgi_id`, `area_km2`, then one column per
    50 m band named by its centre elevation; values are ‰ of the area and
    sum to 1000).
  - G only: `-submission_info.csv` and its metadata JSON, one row per GLIMS
    submission: `subm_id`, `n_outlines`, `area_km2`, `anlys_time`,
    `release_dt`, `proc_desc`, `chief_affl`, `submitters`, `analysts`,
    `rc_id`.
  - G only: `-rgi6_links.csv`, which is wrong (see §5.3).
  - C only: `-CtoG_links.json`, a dict from complex ID to a list of glacier
    IDs. This is the only complex↔glacier link; G has no complex column.
- **The regions zip** holds `o1regions` (`o1region`, `full_name`,
  `long_code`) and `o2regions` (adds `o2region`) shapefiles, plus
  `-o1regions-summary.csv` and `-o2regions-summary.csv`. The builder reads
  the summary columns.
- **How the products link:**
  - L → G through `rgi_g_id`.
  - I → G through `rgi_g_id_1` and `rgi_g_id_2`.
  - C ↔ G only through the JSON file above.
- **Junk in the zips:** `.ipynb_checkpoints/` folders, and one `README.md` per
  zip.
- **Antimeridian:** no single glacier wraps around ±180°. Region 10 has 27
  glaciers within 1° of it. The region outlines that cross the antimeridian
  (10, 19-15, 20) are pre-split.
- **Glacier names:** 57,996 glaciers have a non-empty `glac_name`. About
  18,400 of those are `S/N` (no name) and about 23,500 contain a Chinese
  inventory code (`CN5…`), some of them alone and some as a prefix to a real
  name. Many names are in capitals (`GROSSER ALETSCH GLETSCHER`) or carry
  other inventory codes (`Marmolada IT4L00101101`,
  `FR4N01236A01 Mer de Glace/Geant`). About 330 are garbled by encoding
  errors.

### 4.2 Where the bytes come from

- **Authoritative distribution:** NSIDC, `nsidc0770_rgi_v7`
  (DOI [10.5067/F6JMOVY5NAVZ](https://doi.org/10.5067/F6JMOVY5NAVZ)),
  behind an Earthdata login.
- **Same release tree with no login:** Fabien Maussion's server at
  `https://cluster.klima.uni-bremen.de/~fmaussion/misc/rgi7_data/rgi7_final/`.
  It holds `global_files/RGI2000-v7.0-{G,C,I,L}-global.zip` and
  `RGI2000-v7.0-regions.zip`.
- **Corrected RGI6 links:**
  `…/rgi7_data/rgi7_rgi6_links/RGI2000-v7.0-G-global-rgi6_links.csv`
  (GLIMS-RGI/rgi_issue_tracker#41).
- **Decision (Claude's call):**
  - The download step fetches from the Bremen server. The repository pins
    every input by URL, sha256 and size, and the build refuses a mismatch.
  - Before pinning, the builder confirms that the Bremen global zips are
    byte-identical to NSIDC's. The author has NSIDC copies of the four global
    zips in `~/.cache/deep-glacier-mapping/raw/glaciers/`. Record the result
    in the provenance document.
  - If they differ, use the NSIDC bytes (with Earthdata `.netrc`) and stop to
    ask.
- The pins live in a tracked file, e.g. `metadata/sources.yaml`, beside the
  RGI version they belong to.

## 5. Data design

### 5.1 Principles

- One file per kind of feature. A row means one thing: a glacier, a complex,
  a centerline segment, an intersect, a region.
- Side tables are folded into the row they describe, as columns. They are not
  published as separate tables.
- **The reference for "RGI's value" (Claude's call):**
  - Attributes come from the `-attributes.csv` files, which carry full
    decimal text. Geometries come from the shapefiles. The two are joined on
    `rgi_id`.
  - Measured on region 11: the `.dbf` floats differ from the CSV by at most
    7e-15, which is DBF text rounding. Every other column agrees.
  - The build asserts that both sources hold the same IDs, and that their
    floats agree within 1e-12.
- Every upstream column keeps its RGI name and its value. Types become
  precise: dates as dates, codes as strings, integers as integers.
  - **Floats stay float64.** Downcasting to float32 would change values. The
  author's earlier loader in `deep-glacier-mapping` did this; do not copy it.
  - Integer narrowing is allowed only where it is lossless; the build asserts
    that.
- Geometries stay in EPSG:4326, 2D.
- Derived columns are few, named in §5.2, and documented as derived.

### 5.2 Files

All paths are relative to `v7.0/`. *Claude's call:* file names repeat the
version (`rgi7.0-glaciers.parquet`), so a downloaded file stays
self-describing.

**`glaciers/rgi7.0-glaciers.parquet`: one row per glacier (274,531).**

| Column(s) | Source | Notes |
| --- | --- | --- |
| the 28 upstream attributes (`rgi_id` … `lmax_m`) | G shapefile / attributes CSV | values unchanged; `glac_name` with the encoding repair (§5.3) |
| `display_name` | **derived** from `glac_name` | §5.4; null when there is no usable name |
| `complex_id` | `-CtoG_links.json` | the complex this glacier belongs to |
| hypsometry | `-hypsometry.csv` | one list column of ‰ values plus the elevation of its first band; the band width (50 m) is documented. Exact shape is the builder's call, e.g. `hypso_z0_m: int32` + `hypso_permille: list<int16>`. Leading and trailing empty bands may be trimmed. A round trip to the CSV must be exact |
| RGI6 links | corrected links CSV | a list of structs per glacier (`rgi6_id`, `overlap_area_km2`, `rgi7_area_fraction`, `rgi6_area_fraction`, plus the cluster fields), empty when there is no link |
| submission | `-submission_info.csv` joined on `subm_id` | flat columns (`subm_n_outlines`, `subm_anlys_time`, `subm_release_dt`, `subm_proc_desc`, `subm_chief_affl`, `subm_submitters`, `subm_analysts`, `subm_rc_id`; exact naming is the builder's call). Parquet's dictionary encoding stores the repeated text once per row group |
| `geometry` | outline | 2D |

**`complexes/rgi7.0-complexes.parquet`: one row per complex (192,869).** The
upstream attributes plus `glacier_ids: list<string>`, the members from the
links JSON.

**`centerlines/rgi7.0-centerlines.parquet`** and
**`intersects/rgi7.0-intersects.parquet`:** the upstream attributes and
geometry, typed. Nothing is folded in: their rows are line segments that
reference glaciers by ID.

**`regions/rgi7.0-regions.parquet`: first- and second-order regions in one
file.** It has a `level` column (1 or 2), the upstream fields, and the
summary CSV columns joined on the region code.

The regions are published under their own citation: GTN-G (2023),
[10.5904/gtng-glacreg-2023-07](https://doi.org/10.5904/gtng-glacreg-2023-07).

### 5.3 Fixes of known upstream errors

Each fix is applied by the build and listed in `docs/PROVENANCE.md` and in each
affected collection's `processing_notes`, with the affected IDs or counts. The
counts are computed, never typed.

| Fix | Upstream reference |
| --- | --- |
| Drop the Z coordinate (all zero) | rgi_issue_tracker#43 |
| Repair names garbled by encoding: UTF-8 bytes read as Latin-1, and cp437 bytes (`Mont V\x82lan` → `Mont Vélan`). The logic is in `deep-glacier-mapping/src/glacier_mapping/datasets/rgi.py::repair_name`. Reimplement it here; do not import it | observed; affects regions 03, 08, 10, 11, 12 |
| Make the 6 invalid polygons valid, keeping them single polygons | rgi_issue_tracker#48 |
| Replace the shipped RGI6 links with the corrected ones | rgi_issue_tracker#41 |
| Ignore `.ipynb_checkpoints/` and the duplicate per-zip READMEs | #42, #49 |

**Errors the build finds beyond this table (Claude's call):**

- **A listed fix applies wherever the same error recurs.** Examples: mojibake
  in the submission text columns or region names, invalid complex polygons.
  - Implement the encoding repair and the validity repair generically, over
    every text column and every polygon product.
  - Report the computed counts per column and product in PROVENANCE.
- **A new kind of error is not fixed on the builder's own authority.** Record
  it in `known_issues` and raise it at the post-`convert` checkpoint (§10).

**Not fixed, but documented in `known_issues`:**

- duplicate `anlys_id` (#27);
- missing Aleutian (#63) and Greenland (#58) glaciers;
- complex artefacts at divides (#21).

`area_km2` and the other computed attributes are kept as published, never
recomputed.

### 5.4 `display_name`

This is the name drawn on the map, and a convenience column in the Parquet.

- The rules are deterministic, live in code with a table-driven test of real
  examples, and are summarised in the collection's column description.
- **Draft rules** (to be checked against the measured name distribution):
  - **No name** (null) for: `S/N` and its variants; names that are only an
    inventory code (`CN5O261B0076`); purely numeric names; one- to
    three-letter codes (`WA`, `NEF`).
  - **Strip** inventory-code prefixes or suffixes:
    `CN5Y673P0037 Tuomuer Glacier` → `Tuomuer Glacier`,
    `Marmolada IT4L00101101` → `Marmolada`.
  - **Change capitals to normal capitalisation:**
    `GROSSER ALETSCH GLETSCHER` → `Grosser Aletsch Gletscher`.
  - **Underscores to spaces.**
- **Checkpoint:** before tiling, the builder shows the author the rule set,
  the counts per rule and a random sample of before/after pairs. The author
  approves.

### 5.5 GeoParquet settings

- **Write with `gpio` (geoparquet-io).** Geopandas cannot yet write the native
  Parquet geometry type. Settings:
  - GeoParquet **2.0**;
  - zstd at level 15 or higher;
  - **Hilbert** spatial order;
  - a **bbox covering column** as well. PORTO-FMT-008 recommends it, and it
    gives page-level spatial pruning, which the later viewer needs to fetch
    one clicked glacier's row cheaply.
- **Fallback (Claude's call): readability beats the newest format.**
  - Before converting all five products, write the glaciers file as
    GeoParquet 2.0 and read it back with every reader in the chain: DuckDB,
    geopandas, GDAL/QGIS, rashid 0.3.x and the Portolan browser.
  - If any of them cannot read it, write GeoParquet 1.1 (WKB + bbox
    covering). The guide endorses 1.1 for wider reader support. Record why in
    `docs/DESIGN.md`.
  - tippecanoe does not read Parquet. Feed it GeoJSON sequences exported from
    the built Parquet files.
- **Row group size is measured, not guessed.** The guide recommends 50–150 k
  rows per group; Portolan caps it at 150 k (PORTO-FMT-009). For 274 k glacier
  rows, that is only 2–6 groups of roughly 100 MB. The builder measures at
  least two settings and picks with the author:
  1. a full DuckDB scan of one column;
  2. fetching one glacier by bbox over HTTP.

  Record the numbers in `docs/DESIGN.md`. rashid FMT-006/044 (spatial order)
  must pass at the chosen size.
- **Parquet key-value metadata** on each file:
  - the RGI version and the mirror revision;
  - the source zips and their sha256;
  - the citation;
  - a pointer to the catalog.
- `table:columns` on each collection (PORTO-FMT-046):
  - upstream columns take their `description` and `units` from RGI's
    `attributes_metadata.json`, read at render time and never copied by hand;
  - derived and folded-in columns take theirs from `metadata/columns.yaml`.
  - Coded columns (`term_type`, `surge_type`, `primeclass`, `aspect_sec`,
    `conn_lvl`, `dem_source`) get their decoded meanings from the RGI user
    guide, cited.

## 6. Web map archive

### 6.1 Layers

There is one archive, `rgi7.0.pmtiles`. *Claude's call:* it lives in the
glaciers collection directory. The other collections link to it with a
relative href (`../glaciers/rgi7.0.pmtiles`).

Checked against rashid (`src/rashid/rules/viz.py`, commit 123c653): the PMTiles
rules check the link's `type`, a non-empty `pmtiles:layers` and a style asset
on the collection, not where the archive lives. The archive is a `rel: pmtiles`
link, not a data asset, so it does not break the single-file rule
(PORTO-CORE-017).

If rashid 0.3.x flags the shared archive anyway, keep the one archive and
record the finding in `docs/conformance.md` with an upstream issue, as
`glace-catalog` does for its accepted findings.

| Layer | From | Zoom range (to be tuned) |
| --- | --- | --- |
| `regions` | regions file | low zooms, with region names |
| `complexes` | complexes file | low to mid zooms, simplified |
| `glaciers` | glaciers file | mid zooms and up |
| `glacier-labels` | points at `cenlon`/`cenlat` with `display_name` and `area_km2`; per-feature minimum zoom by area | mid zooms and up, larger glaciers earlier |
| `centerlines` | centerlines file | high zooms |
| `intersects` | intersects file | high zooms |

Points that rule the tuning:

- **Label points use RGI's own representative point,** which lies inside the
  outline. No new coordinates are computed.
- **Hand-over targets.** Glaciers are complete (no feature dropped) from about
  z10. Large glaciers are named from about z7, and the smallest only near the
  maximum zoom.
- **Measured constraints.** The first tiles stay small, following the
  `portolan-bootstrap` QC. Tile size stays within tippecanoe's limit without
  silently dropping features at the zoom where they are meant to be complete.
- **tippecanoe reads from the built Parquet files,** so the map cannot drift
  from the data.

### 6.2 Attributes in tiles

- Each layer carries every scalar column of its Parquet file, including
  `display_name`, `complex_id` and the submission columns.
- **Vector tiles cannot store lists,** so the hypsometry, the RGI6 links and
  `glacier_ids` stay in the Parquet only. The later viewer fetches them by
  `rgi_id` when a glacier is clicked.
- If measured tile weight forces more columns out, stop and ask the author.
  Do not drop columns silently. The README states which columns the tiles
  lack and why.

### 6.3 Styles

- Every collection that links the archive needs a `style` asset (rashid
  PTL-VIZ checks; PORTO-FMT-014/015, CORE-069/070). At least:
  - one default style per collection, drawing its own layer;
  - one full-map style showing all layers with labels, the "OSM-like" view.
- **What each style shows is a checkpoint** with the author, following
  `portolan-bootstrap` "Styles That Say Something". Present candidate
  readings with their measured distributions, for example `term_type`
  (land / marine / lake / shelf) or `surge_type`.
- **Legend rule:** the browser draws a legend only for a `fill` layer whose
  `fill-color` is a `match` or `step` expression.

## 7. Catalog design

### 7.1 Tree

```
catalog.json  README.md  AGENTS.md
└── v7.0/                         sub-catalog: catalog.json README.md AGENTS.md
    ├── glaciers/                 collection.json README.md AGENTS.md
    │   ├── rgi7.0-glaciers.parquet      (data)
    │   ├── rgi7.0.pmtiles               (shared archive, rel: pmtiles)
    │   ├── styles/*.json  thumbnail
    ├── complexes/   …parquet  styles/  thumbnail
    ├── centerlines/ …
    ├── intersects/  …
    └── regions/     …
```

- Each collection is a **single-file collection**: its data is one
  collection-level asset, with no items (PORTO-CORE-017).
- Collections never nest (CORE-014). The version level is a catalog.

### 7.2 Mirror declaration and citation

- **Providers on every collection:**
  - RGI Consortium, roles `producer` and `licensor`, url
    `https://www.glims.org/rgi_user_guide/` or `https://rgidata.org`;
  - the host, last: Luis Gentner, url the GitHub repository. The host
    contact is a checkpoint with the author.
  - NSIDC is the distributor and is named in the description and the `via`
    link, not as a provider. *Claude's call.*
- **Links:**
  - a `via` link to the NSIDC landing page,
    `https://nsidc.org/data/nsidc-0770/versions/7` (`text/html`);
  - `cite-as` to the DOI;
  - `updated` set at each build. There is no `canonical`, since RGI has no
    STAC.
- **License:** `CC-BY-4.0`, attested in the RGI user guide introduction.
- **Citation** (`sci:citation`, README, `CITATION.cff`): RGI's dataset
  citation, *RGI 7.0 Consortium, 2023. Randolph Glacier Inventory - A Dataset
  of Global Glacier Outlines, Version 7.0. NSIDC. doi:10.5067/f6jmovy5navz*.
  The user guide (doi:10.5281/zenodo.8362857) is listed as a publication.
  - The centerlines collection also cites Kienholz et al. (2014) and
    Maussion et al. (2019).
  - The regions collection cites GTN-G (2023).
  - The mirror asks for no citation of its own. At most, readers may add
    "accessed via" with the mirror's URL.
- **Source assets** (PORTO-FMT-002): each collection links its upstream zip
  at NSIDC, with role `source` and a title saying it needs an Earthdata
  login. *Claude's call.*
- **Wording (decided):**
  - Every README and every catalog and collection description says plainly,
    near the top, that this is an **unofficial mirror, not endorsed by the
    RGI Consortium**.
  - They also say that RGI at NSIDC is the authoritative source, and that
    citation and credit go to the RGI Consortium, with the citation right
    there.
  - Follow the tone of `portolan-mirrors/firms-catalog` and link
    `docs/PROVENANCE.md`.
  - A test checks that the disclaimer appears in every rendered README and
    description, so a template edit cannot drop it.
- **Navigation:** apply the Portolan navigation contract (`portolan-bootstrap`
  `reference/catalog-navigation.md`): data browser `alternate`, `vcs`,
  `issues`, and `about` → `https://source.coop/lqgentner/rgi`. The host's
  `url` is the GitHub repository.
  - **Decided:** the repository goes public right after the first upload,
    when the link is shared with the RGI people. The `vcs` and `issues` links
    are therefore present from the start, and the brief window in which they
    lead to a private repository is accepted.
  - Any external-link check that probes GitHub may fail until then. Do not
    add a switch to suppress the links.

### 7.3 Documentation

Follow the `portolan-bootstrap` documentation contract:

- Every catalog and collection has a README and an `AGENTS.md`.
- The `AGENTS.md` files carry the join keys and runnable DuckDB recipes. For
  example: find a glacier by name, get the Rhone glacier with its
  hypsometry, all glaciers of a region over 10 km², a complex with its
  member glaciers, and the centerlines of a glacier.
- **Every documented query is executed by a test** (`git-backed-catalog`,
  "Test the documented queries and claims") against a base URL:
  - the local preview before upload;
  - the public URL after upload.

## 8. Repository and pipeline

### 8.1 Starting point

- The GitHub repository `lqgentner/rgi-catalog` (private) was created from
  `portolan-sdi/portolan-catalog-template`. `~/Repositories/rgi-catalog/` is
  its checkout on `main`, with this design document added.
- Work through the template's `SETUP.md`, as the `git-backed-catalog` skill
  says.
- Remove the template parts meant for the `portolan-sdi` organisation
  (SETUP step 10).
- Raise the rashid gate to the pinned 0.3.x, as the skill describes.

### 8.2 Metadata sources and rendering (decided: yes, smaller than GLACE)

- **The one deliberate departure from the template:** `catalog/` is
  **generated and committed**, not hand-edited.
- **Tracked sources:**
  - `metadata/catalog.yaml`: titles, prose, providers, citations, license,
    links, public base, and the RGI versions present;
  - `metadata/columns.yaml`: only the derived and folded-in columns;
  - `metadata/sources.yaml`: the upstream pins (§4.2);
  - `metadata/builds/v7.0.json`, **written by the build and committed:**
    file sizes, checksums, extents, row counts, the mirror revision, the
    build date. It is what makes `catalog/` fully determined by tracked
    files;
  - templates for the README and AGENTS files.
- **A render step** combines these with RGI's `attributes_metadata.json`
  (read from the pinned download) into `catalog/`.
- **A test fails when `catalog/` differs from a fresh render.** That is the
  drift guard. Running the render twice must make no changes.
- `docs/DESIGN.md` records the deviation from the template's
  hand-edited flow.

### 8.3 Build

- **Pixi tasks.** The exact names are the builder's call. Every step is
  rerunnable.
  1. `download`: fetch and verify against the pins, into a local cache
     outside git.
  2. `convert`: build the five Parquet files into a staging directory laid
     out like `catalog/` (§7.1).
  3. `tiles`: build the PMTiles archive from the staged Parquet files.
  4. `render`: write the build record and render `catalog/`.
  5. `thumbnails`: follow the `portolan-thumbnails` skill (chiitiler, Node
     ≥ 24.12). Thumbnails are small and committed in `catalog/`.
- **Asset hrefs in `catalog/` are relative.** The staging directory mirrors
  the catalog layout, so catalog and data line up under one root, locally and
  once published. The root `self` link is absolute, from the public base
  (CORE-081). The `s3://` form goes in the alternate-assets extension
  (CORE-024).
- **Dependencies:**
  - geopandas, pyarrow and shapely for assembly;
  - geoparquet-io for writing;
  - tippecanoe;
  - DuckDB for profiling and the query tests;
  - rashid 0.3.x;
  - jinja2 and pyyaml;
  - pytest, ruff and pyrefly (strict).
  - freezebase is not needed. *Claude's call.*
  - Nothing is imported from `deep-glacier-mapping`.

**Order (Claude's call): a vertical slice first.** Build the glaciers file
and the archive's glacier and label layers all the way to a local preview.
The other four products come after. That gives a demo early and surfaces the
format risks (§5.5, §6.1) before most of the work is done.

### 8.4 Local preview

- A small static server serves the tracked `catalog/` overlaid with the
  staging directory, as one tree. It must honour HTTP Range and send CORS
  headers. Plain `python -m http.server` ignores Range, which is why
  `firms-catalog` ships `apps/firms-preview/serve.py`.
- Run the Portolan browser locally (`portolan-sdi/portolan-browser`,
  `pnpm start`, `SB_catalogUrl=http://localhost:<port>/catalog.json`) against
  it.
- Run rashid on the assembled tree, reading data bytes (`--data`).
- Run the documented queries against the local URL.
- **The builder walks the `portolan-bootstrap` quality-control list here:**
  - the default styles render;
  - legends match the data;
  - the bbox is tight;
  - the first tile weight is acceptable;
  - the thumbnails show data;
  - the links resolve.

### 8.5 Publish

- Use the template's `tools/publish.py` (catalog documents) and
  `tools/upload_data.py` (the staging directory). Configure them in
  `catalog.publish.yaml`:
  - `write_prefix: s3://lqgentner/rgi`;
  - `public_base: https://data.source.coop/lqgentner/rgi`;
  - the `source-coop` profile;
  - `data_dir` = the staging directory.
- Dry run first. **Uploading is a checkpoint with the author:** file count,
  size, destination, warnings.
- After the upload, run `rashid check --live` against the public base, and the
  documented queries against the public URL. Then open the root and one
  collection in the hosted Portolan browser.
- A mirror revision is the same loop, followed by a git tag, a changelog
  entry and a bumped `version`.

### 8.6 CI

- The template's CI (`CI_LIGHT=1`) runs on every push:
  - lint, type check and unit tests (the `display_name` rules, name repair,
    hypsometry round trip, lossless typing);
  - the render-drift test;
  - rashid on `catalog/`;
  - the link checks.
- The query tests against the public URL run on dispatch and after uploads.

## 9. Left to the builder

- Exact column names and dtypes for the folded-in data. The constraints are
  in §5.2: round trips exact, values unchanged.
- tippecanoe parameters, zoom ranges, simplification and the label
  minimum-zoom thresholds, within §6.
- Module layout, task names, test structure.
- The local preview server's implementation.
- The wording of README, AGENTS and PROVENANCE, within the
  `portolan-bootstrap` documentation contract and §7.2.

## 10. Checkpoints with the author

| When | Present | Ask |
| --- | --- | --- |
| Before pinning sources | Bremen vs NSIDC checksum comparison | Proceed with Bremen as the download source? |
| After `convert` | Row counts, sizes, fix counts, row-group measurements | Pick the row group size |
| Before tiling | `display_name` rules, counts, sample | Approve the rules |
| Before tiling | Style plan with measured distributions | Approve the styles |
| After preview QC | QC checklist and grader tiers | Fix or publish? |
| Before the first upload | — | The author creates the `rgi` product on source.coop (web UI) and sets its title, description and visibility |
| Before upload | File count, size, destination, warnings; host contact | Upload? |
