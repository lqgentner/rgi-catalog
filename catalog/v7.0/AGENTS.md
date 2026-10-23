# AGENTS.md: RGI 7.0

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Collections

- `glaciers/`: 274,531 rows in
  `https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet`.
  Read `glaciers/AGENTS.md` for its columns, join keys and recipes.

## Join keys

`rgi_id` is unique in every collection. Each glacier ID has the form
`RGI2000-v7.0-G-<o1region>-<number>`.

## Versions

The mirror revision (`7.0-r1`) counts rebuilds of this
mirror. It is not an RGI version. The collection field `version` and the
footer key `rgi:mirror_revision` of each file carry it.
