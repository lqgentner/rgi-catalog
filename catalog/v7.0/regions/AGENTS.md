# AGENTS.md: RGI 7.0 glacier regions

**Each claim here is quoted from a source or measured from the data.** Keep
this rule when you edit the file.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## About the product

The RGI 7.0 user guide describes the
[rgi glacier regions](https://rgidata.org/user_guide/02_regions_definition.html):

<!-- human-written -->

> RGI outlines are organized into 20 first-order glacier regions. This is one more than in RGI 6.0 and earlier versions, since former region 19 was split into two regions (global map; Table 1a). These are further subdivided into second-order regions, of which there are 90 in total in RGI 7.0 (Table 1b). Glacier regions are useful for regional assessments of glacier change and other variables.

<!-- /human-written -->

## The file

`https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet`: 110
rows, one per region. The column descriptions are in
`assets.data["table:columns"]` of `collection.json`, with RGI's own text for
the upstream columns. Coded columns carry their meanings in
`classification:classes`. Their descriptions leave out RGI's pointer to the
user guide.

## Recipes

Each recipe runs as written in DuckDB. Load the extensions once:

```sql
INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;
SELECT 1;
```

The first-order regions:

```sql
SELECT o1region, full_name, long_code
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet'
WHERE level = 1
ORDER BY o1region;
```

The glacier count and area of each second-order region:

```sql
SELECT r.o2region, r.full_name,
       count(g.rgi_id) AS n_glaciers, sum(g.area_km2) AS area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet' AS r
LEFT JOIN 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet' AS g ON g.o2region = r.o2region
WHERE r.level = 2
GROUP BY r.o2region, r.full_name
ORDER BY area_km2 DESC NULLS LAST;
```

The region a point lies in:

```sql
SELECT level, o1region, o2region, full_name
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet'
WHERE ST_Contains(geometry, ST_Point(8.0, 46.5));
```

## Join keys

- `level` is 1 or 2. `o1region` is set on every row. `o2region` is null
  where `level = 1`. One row is one region: `o1region` is unique where
  `level = 1`, and `o2region` is unique where `level = 2`.
- `glaciers.o1region` joins `o1region` where `level = 1`, and
  `glaciers.o2region` joins `o2region` where `level = 2`. Every glacier and
  every complex has an `o2region` that is in this file.
- `long_code` is the name of RGI's region files, such as
  `11_central_europe`.

## Usage notes

- "the region outlines of `10` and `19-15` appear in the accompanying
  shapefiles as two polygons, eastern and western." Here each is one row,
  a MultiPolygon of both parts. Its bounding box spans almost every
  longitude, so a bbox filter always reads it.
- The `regions` layer of the web map archive draws each shared border
  twice, once per polygon. The `region-boundaries` layer stores each border
  once, as lines with one column, `level`: 1 where the line bounds a
  first-order region, else 2. Its lines are snapped to 1e-5 degrees, so
  they are not exact copies of the polygon outlines. It leaves out the
  edges that close regions 10, 19, 19-15, 20 and 20-01 at the antimeridian.
- Region 20 (Antarctic Mainland) and the second-order regions 19-23 and
  20-01 have no glaciers.
- The regions are GTN-G's, not the RGI Consortium's. Cite them as the
  README says.
