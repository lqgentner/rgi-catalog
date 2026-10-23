# AGENTS.md: RGI 7.0 glacier complexes

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## The file

`https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet`: 192,869
rows, one per glacier complex. The column descriptions are in
`assets.data["table:columns"]` of `collection.json`, with RGI's own text for
the upstream columns. Coded columns carry their meanings in
`classification:classes`.

## Recipes

Each recipe runs as written in DuckDB. Load the extensions once:

```sql
INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;
SELECT 1;
```

The complex of the Rhone glacier and its member glaciers:

```sql
SELECT rgi_id, area_km2, unnest(glacier_ids) AS glacier_id
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet'
WHERE rgi_id = 'RGI2000-v7.0-C-11-01208';
```

The complexes with the most glaciers:

```sql
SELECT rgi_id, o1region, len(glacier_ids) AS n_glaciers, area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet'
ORDER BY n_glaciers DESC
LIMIT 10;
```

The glaciers of a complex, with their names, through the glaciers file:

```sql
SELECT g.rgi_id, g.display_name, g.area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet' AS g
WHERE g.complex_id = 'RGI2000-v7.0-C-11-01208'
ORDER BY g.area_km2 DESC;
```

## Join keys

- `rgi_id` is unique: 192,869
  distinct values.
- `glacier_ids` holds the `rgi_id` of each member glacier, sorted. Every
  glacier is in exactly one complex: the lists hold 274,531 distinct glacier
  IDs, and `glaciers.complex_id` names the same complex.

## Quirks that produce silently wrong answers

- A complex is "the result of a spatial merge operation of the glacier
  product": "any cluster of connected glaciers (however small the
  connection) will be merged into one entity". 171,009 complexes hold one
  glacier. The largest, `RGI2000-v7.0-C-01-09429`, holds 893.
- The complexes have "the same area but a smaller or equal number of
  entities as the glacier product". Do not add complex and glacier areas.
- 7 complex outlines were invalid and are repaired, each to one valid
  polygon: `RGI2000-v7.0-C-01-06260`, `RGI2000-v7.0-C-13-29773`,
  `RGI2000-v7.0-C-13-39954`, `RGI2000-v7.0-C-13-53377`,
  `RGI2000-v7.0-C-14-16384`, `RGI2000-v7.0-C-15-05787` and
  `RGI2000-v7.0-C-18-01642`.
