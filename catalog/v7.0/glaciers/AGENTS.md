# AGENTS.md: RGI 7.0 glaciers (unofficial mirror)

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is RGI at NSIDC (https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium: RGI 7.0 Consortium, 2023. Randolph Glacier Inventory - A Dataset of Global Glacier Outlines, Version 7.0. Boulder, Colorado USA. NSIDC: National Snow and Ice Data Center. doi:10.5067/f6jmovy5navz.

## The file

`https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet`: 274,531
rows, one per glacier. The column descriptions are in
`assets.data["table:columns"]` of `collection.json`, with RGI's own text for
the upstream columns. Coded columns carry their meanings in
`classification:classes`.

## Recipes

Each recipe runs as written in DuckDB. Load the extensions once:

```sql
INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;
SELECT 1;
```

Find a glacier by name. `display_name` is cleaned for labels, `glac_name` is
RGI's value:

```sql
SELECT rgi_id, glac_name, display_name, o1region, area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet'
WHERE display_name ILIKE '%aletsch%'
ORDER BY area_km2 DESC;
```

The hypsometry of the Rhone glacier, one row per 50 m band. DuckDB lists
start at 1, so the band `i` has the central elevation
`hypso_z0_m + 50 * (i - 1)`:

```sql
SELECT rgi_id,
       hypso_z0_m + 50 * (generate_subscripts(hypso_permille, 1) - 1) AS band_center_m,
       unnest(hypso_permille) AS permille
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet'
WHERE rgi_id = 'RGI2000-v7.0-G-11-01706';
```

All glaciers of first-order region 11 (Central Europe) larger than 10 km²:

```sql
SELECT rgi_id, display_name, area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet'
WHERE o1region = '11' AND area_km2 > 10
ORDER BY area_km2 DESC;
```

The glaciers in a box. The `bbox` filter lets DuckDB skip row groups, and
`ST_Intersects` checks the outlines:

```sql
SELECT rgi_id, display_name, area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet'
WHERE bbox.xmin < 8.1 AND bbox.xmax > 7.9 AND bbox.ymin < 46.6 AND bbox.ymax > 46.4
  AND ST_Intersects(geometry, ST_MakeEnvelope(7.9, 46.4, 8.1, 46.6));
```

The RGI 6.0 outlines that overlap one glacier:

```sql
SELECT rgi_id, link.rgi6_id, link.overlap_area_km2, link.rgi7_area_fraction
FROM (SELECT rgi_id, unnest(rgi6_links) AS link FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet')
WHERE rgi_id = 'RGI2000-v7.0-G-11-01706';
```

## Join keys

- `rgi_id` is unique: 274,531
  distinct values.
- `glims_id` is not unique: 274,326 distinct values in 274,531 rows. Do not
  join on it.
- `complex_id` holds the `rgi_id` of the glacier complex. Every glacier has
  one.
- `rgi6_links[].rgi6_id` holds RGI 6.0 IDs (`RGI60-…`).
- `subm_id` identifies a GLIMS submission. The `subm_*` columns are its
  attributes, from the glacier's first-order region.

## Quirks that produce silently wrong answers

- `term_type` 9 means "Not assigned", not land-terminating. RGI 7.0 assigns
  only the marine-terminating class (1,561 glaciers).
- `display_name` is null for every glacier without a usable name. 9,467
  glaciers have one, and 57,996 have a non-empty `glac_name`.
- `rgi6_links` is an empty list, not null, for the 52,855 glaciers without an
  RGI 6.0 overlap.
- `subm_n_outlines` counts the submission's outlines in the glacier's
  first-order region, not in all regions.
- `hypso_permille` leaves out empty bands below the lowest and above the
  highest glacierized band. Its values sum to 1000.
- No outline crosses the antimeridian. Region 10 has glaciers near ±180°, so
  a box from 170° to -170° must be split in two.
