# AGENTS.md: RGI 7.0 glacier centerlines

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## About the product

The RGI 7.0 user guide describes the
[glacier centerlines product](https://rgidata.org/user_guide/products/centerlines_product.html):

> The glacier centerlines product contains geometrical centerlines for the main branches and major tributaries of all glaciers in the RGI 7.0 glacier product. The centerlines are computed using a geometrical flow routing algorithm first described by Kienholz et al. [2014] and implemented and executed by the Open Global Glacier Model (OGGM) [Maussion et al., 2019].

## The file

`https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet`: 367,724
rows, one per centerline. The column descriptions are in
`assets.data["table:columns"]` of `collection.json`, with RGI's own text for
the upstream columns. Coded columns carry their meanings in
`classification:classes`.

## Recipes

Each recipe runs as written in DuckDB. Load the extensions once:

```sql
INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;
SELECT 1;
```

The main centerline of the Rhone glacier:

```sql
SELECT rgi_id, segment_id, length_m, ST_AsText(geometry) AS wkt
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet'
WHERE rgi_g_id = 'RGI2000-v7.0-G-11-01706' AND is_main;
```

The centerlines of one glacier, tributaries first:

```sql
SELECT rgi_id, segment_id, is_main, outflow_id, strahler_n, length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet'
WHERE rgi_g_id = 'RGI2000-v7.0-G-11-01706'
ORDER BY segment_id;
```

The longest main centerlines, with the glacier names:

```sql
SELECT l.rgi_g_id, g.display_name, l.length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet' AS l
JOIN 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet' AS g ON g.rgi_id = l.rgi_g_id
WHERE l.is_main
ORDER BY l.length_m DESC
LIMIT 10;
```

## Join keys

- `rgi_id` is unique: 367,724
  distinct values.
- `rgi_g_id` joins `glaciers.rgi_id`. Every glacier has exactly one row with
  `is_main` true, so a join on the main centerline keeps one row per glacier.
- `outflow_id` "points to the `segment_id` to which this centerline flows
  to", within the same glacier. Join on `rgi_g_id` and `segment_id`, never
  on `segment_id` alone.

## Quirks that produce silently wrong answers

- The main centerline is "always last": it has the highest `segment_id` of
  its glacier. Its `outflow_id` is -1. The other centerlines have an
  `outflow_id` from 1 to 107.
- `length_m` of the main centerline equals the glacier's `lmax_m` for all
  274,531 glaciers. "The main (i.e.longest) centerline is used to compute
  the glacier product's maximum length attribute `lmax_m`."
- RGI's description of `rgi_id` reads "Unique identifier assigned to a
  single intersect line". It identifies a centerline.
- "it is likely that centerlines on individual glaciers would be drawn
  differently by a human or other algorithms."
