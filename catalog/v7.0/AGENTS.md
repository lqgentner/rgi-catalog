# AGENTS.md: RGI 7.0

**Each claim here is quoted from a source or measured from the data.** Keep
this rule when you edit the file.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Collections

- `glaciers/`: 274,531 rows in
  `https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet`.
  Read `glaciers/AGENTS.md` for its columns, join keys and recipes.
- `complexes/`: 192,869 rows in
  `https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet`.
  Read `complexes/AGENTS.md` for its columns, join keys and recipes.
- `intersects/`: 130,429 rows in
  `https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet`.
  Read `intersects/AGENTS.md` for its columns, join keys and recipes.
- `centerlines/`: 367,724 rows in
  `https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet`.
  Read `centerlines/AGENTS.md` for its columns, join keys and recipes.
- `regions/`: 110 rows in
  `https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet`.
  Read `regions/AGENTS.md` for its columns, join keys and recipes.

## Join keys

`rgi_id` is unique in the glacier, complex, intersect and centerline
products. The region product has no `rgi_id`.
Each ID has the form `RGI2000-v7.0-<X>-<o1region>-<number>`.
The letter `X` identifies the product: `G` for glaciers, `C` for complexes,
`I` for intersects and `L` for centerlines.

- `glaciers.complex_id` joins `complexes.rgi_id`.
  `complexes.glacier_ids` lists the same links from the other side.
- `centerlines.rgi_g_id` joins `glaciers.rgi_id`.
- `intersects.rgi_g_id_1` and `intersects.rgi_g_id_2` each join
  `glaciers.rgi_id`.
- `glaciers.o1region` joins `regions.o1region` where `level = 1`, and
  `glaciers.o2region` joins `regions.o2region` where `level = 2`. The
  complexes have the same two codes.

## Versions

The mirror revision (`7.0-r1`) counts rebuilds of this
mirror. It is not an RGI version. The collection field `version` and the
footer key `rgi:mirror_revision` of each file carry it.
