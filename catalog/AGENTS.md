<!-- vale Portolan-Mechanics.Headings = NO -->
# AGENTS.md: Randolph Glacier Inventory Mirror
<!-- vale Portolan-Mechanics.Headings = YES -->

Guidance for AI agents and automated clients working with this catalog.

**Each claim here is quoted from a source or measured from the data.** Keep
this rule when you edit the file.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Contents of the catalog

The public root is `https://data.source.coop/lqgentner/rgi/catalog.json`. Each RGI version is a
sub-catalog. Each RGI product is a collection with one GeoParquet file and no
items. The glaciers collection also has a names table: a plain Parquet file
of each glacier's ID, names and region codes.

- `v7.0/`: RGI 7.0, mirror revision `7.0-r1`. Collections: `glaciers`, `complexes`, `intersects`, `centerlines`, `regions`. Read `v7.0/AGENTS.md` next.

## How to read it

Query the GeoParquet files in place with DuckDB. Each collection's
`AGENTS.md` has tested recipes. Read the column descriptions from
`assets.data["table:columns"]` in the collection JSON.

```sql
INSTALL httpfs; LOAD httpfs;
SELECT count(*) AS glaciers
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet';
```

## Usage notes

- `rgi_id` is the only stable key. Never derive an ID from a name.
- The mirror keeps RGI's values. For a value that looks wrong,
  check [docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md)
  and the RGI user guide before you correct it.
