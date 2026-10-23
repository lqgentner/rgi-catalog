# AGENTS.md: RGI 7.0 glacier intersects

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## The file

`https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet`: 130,429
rows, one per intersect. The column descriptions are in
`assets.data["table:columns"]` of `collection.json`, with RGI's own text for
the upstream columns. Coded columns carry their meanings in
`classification:classes`.

## Recipes

Each recipe runs as written in DuckDB. Load the extensions once:

```sql
INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;
SELECT 1;
```

The divides of the Rhone glacier and the glacier on the other side:

```sql
SELECT rgi_id,
       CASE WHEN rgi_g_id_1 = 'RGI2000-v7.0-G-11-01706' THEN rgi_g_id_2 ELSE rgi_g_id_1 END
         AS neighbour,
       length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet'
WHERE 'RGI2000-v7.0-G-11-01706' IN (rgi_g_id_1, rgi_g_id_2);
```

The total divide length between each pair of glaciers. A pair can share
more than one line:

```sql
SELECT least(rgi_g_id_1, rgi_g_id_2) AS glacier_a,
       greatest(rgi_g_id_1, rgi_g_id_2) AS glacier_b,
       count(*) AS n_lines, sum(length_m) AS length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet'
GROUP BY ALL
ORDER BY length_m DESC
LIMIT 10;
```

## Join keys

- `rgi_id` is unique: 130,429
  distinct values.
- `rgi_g_id_1` and `rgi_g_id_2` each join `glaciers.rgi_id`. "the choice of
  which glacier is listed as 1 is arbitrary", so match a glacier on both
  columns.

## Quirks that produce silently wrong answers

- 14,035 glacier pairs share more than one intersect line. Count the pairs
  with `least`/`greatest`, not the rows.
- 103,528 glaciers have an intersect. A glacier without one touches no
  other glacier.
- `length_m` is a float, in m, from 0.0066 to 61,211. The centerlines'
  `length_m` is an integer.
