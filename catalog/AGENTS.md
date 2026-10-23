# AGENTS.md: Randolph Glacier Inventory Mirror

Guidance for AI agents and automated clients working with this catalog.

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## What this catalog holds

The public root is `https://data.source.coop/lqgentner/rgi/catalog.json`. Each RGI version is a
sub-catalog. Each RGI product is a collection with one GeoParquet file and no
items.

- `v7.0/`: RGI 7.0, mirror revision `7.0-r1`. Collections: `glaciers`, `complexes`, `centerlines`, `intersects`, `regions`. Read `v7.0/AGENTS.md` next.

## How to read it

Query the GeoParquet files in place with DuckDB. Each collection's
`AGENTS.md` has tested recipes. Read the column descriptions from
`assets.data["table:columns"]` in the collection JSON.

```sql
INSTALL httpfs; LOAD httpfs;
SELECT count(*) AS glaciers
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet';
```

## Quirks that produce silently wrong answers

- `rgi_id` is the only stable key. Never derive an ID from a name.
- This is a mirror. The values are RGI's. For a value that looks wrong,
  check [docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md)
  and the RGI user guide before you correct it.
