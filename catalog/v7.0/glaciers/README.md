# RGI 7.0 glaciers

[Open in data browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/glaciers/collection.json) · [Source repository](https://github.com/lqgentner/rgi-catalog) · [Report a problem](https://github.com/lqgentner/rgi-catalog/issues) · [Hosting repository](https://source.coop/lqgentner/rgi)

One row per glacier: the outline, RGI's attributes, the hypsometry, the links to RGI 6.0 and the GLIMS submission, in one GeoParquet file. A web map archive holds the outlines and the glacier names.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Files

- [`rgi7.0-glaciers.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet): 274,531 rows, 258.0 MB. GeoParquet 2.0.0 in 24 row groups of up to 12,122 rows, zstd-compressed and ordered along a Hilbert curve. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the web map archive (PMTiles, vector tiles, z0 to z12), with the layers `glaciers`, `glacier-labels`. Below z10 the layer is an overview: up to z6 each feature is a point, one per grid cell, and at z7 and z8 a feature too small to draw is a square. Overview features carry only `rgi_id`, `display_name`, `area_km2`, `zmed_m`, `surge_type`, `term_type`, `is_rgi6`. From z10 the tiles carry every column except the list and struct columns, which vector tiles cannot store: `hypso_permille`, `rgi6_links`, `bbox`. Fetch those from the GeoParquet file by `rgi_id`. Timestamps are strings in the tiles.
## Map styles

- [Reference map](./styles/reference.json) (default): Glacier outlines (blue) and centerlines (red), with glacier names and the boundaries and names of the glacier regions. Larger glaciers are named at lower zooms.
- [Median elevation](./styles/median-elevation.json): Glaciers coloured by median elevation (zmed_m) in 1,000 m classes, from below 1,000 m (dark purple) to 5,000 m and above (yellow).
- [Surge evidence](./styles/surge-evidence.json): Glaciers coloured by the evidence for surging (surge_type): no evidence, possible, probable or observed.
- [Terminus type](./styles/terminus-type.json): Glaciers coloured by terminus type (term_type). RGI 7.0 assigns only the marine-terminating class. Every other glacier is not assigned.
- [Same as RGI 6.0](./styles/same-as-rgi6.json): Glaciers coloured by whether the outline is the same as in RGI 6.0 (is_rgi6) or new in RGI 7.0, as in the map of the RGI 7.0 user guide.

## Access

No account and no download are needed. This DuckDB query reads one glacier:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT rgi_id, display_name, area_km2, zmed_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet'
WHERE rgi_id = 'RGI2000-v7.0-G-11-01706';
```

`glaciers/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet`.

## Columns

| Column | Type | Description |
| --- | --- | --- |
| `rgi_id` | `string` | Unique identifier assigned to a single outline. |
| `o1region` | `string` | The code of the first-order region to which the glacier belongs. |
| `o2region` | `string` | The code of the second-order region to which the glacier belongs. |
| `glims_id` | `string` | Non-unique identifier assigned to glaciers by the Global Land Ice Measurements from Space service at NSIDC. |
| `anlys_id` | `uint32` | The unique identifier assigned within GLIMS for a particular outline of a glacier at a particular time. |
| `subm_id` | `uint16` | Unique identifier assigned by GLIMS to a specific data submission. Allows to obtain information about the analysts and data submitters. |
| `src_date` | `timestamp[us]` | The as-of date for the outline (usually the acquisition date of the image), in the format ISO 8601. (date) |
| `cenlon` | `double` | Longitude of an approximately central point within the glacier outlines (not the centroid). (degrees) |
| `cenlat` | `double` | Latitude of an approximately central point within the glacier outlines (not the centroid). (degrees) |
| `utm_zone` | `uint8` | Number of the UTM zone for this glacier, based on its representative point. Note that this attribute is for information only, the geometries are all in WGS84. |
| `area_km2` | `double` | Area of the glacier. (km2) |
| `primeclass` | `uint8` | WGMS primary classification of the glacier. For a categories description, see user guide. |
| `conn_lvl` | `uint8` | Level of connection to the Greenland Icesheet (0: no connection; 1: weak connection). |
| `surge_type` | `uint8` | Flag indicating if surging behavior has been documented for this glacier. For a categories description, see user guide. |
| `term_type` | `uint8` | Flag indicating the terminus type of the glacier. For a categories description, see user guide. |
| `glac_name` | `string` | Glacier name (when available). |
| `is_rgi6` | `bool` | Flag indicating if the outline is the same as in RGI 6.0 (1) or was remapped (0). Note that it does not guarantee strict equivalence of the polygon (in most of the cases it does). |
| `termlon` | `double` | Longitude of the lowest elevation point on the glacier outline. (degrees) |
| `termlat` | `double` | Latitude of the lowest elevation point on the glacier outline. (degrees) |
| `zmin_m` | `double` | Minimum elevation (m above sea level) of the glacier. (m) |
| `zmax_m` | `double` | Maximum elevation (m above sea level) of the glacier. (m) |
| `zmed_m` | `double` | Median elevation (m above sea level) of the glacier. (m) |
| `zmean_m` | `double` | Mean elevation (m above sea level) of the glacier. (m) |
| `slope_deg` | `double` | Mean slope of the glacier surface. (degrees) |
| `aspect_deg` | `double` | The aspect (orientation) of the glacier surface presented as an azimuth relative to 0° at due north. (degrees) |
| `aspect_sec` | `uint8` | The aspect (orientation) of the glacier surface presented as a category. For a categories description, see user guide. |
| `dem_source` | `string` | The name of the dataset that was used to compute the topography attributes. |
| `lmax_m` | `uint32` | Length (m) of the longest surface centerline of the glacier. (m) |
| `display_name` | `string` | Derived from glac_name for map labels: inventory codes such as CN5Y673P0037 removed, names in capitals re-cased, and placeholders such as S/N set to null. Null when no usable name is left. glac_name keeps RGI's value. The rules are in docs/PROVENANCE.md. |
| `complex_id` | `string` | The rgi_id of the glacier complex that holds this glacier, from the CtoG_links.json file of the glacier complex product. That file links "the glacier complex to the glacier products, in a JSON dictionary". |
| `hypso_z0_m` | `int32` | Central elevation of the first band of hypso_permille, in m. The band n has the central elevation hypso_z0_m + 50 * n. "The elevation bands are all 50 m in height." (m) |
| `hypso_permille` | `list<element: int16>` | The glacier's hypsometry from the hypsometry.csv file: "elevation-band areas in the form of integer thousandths of the glacier's total area in km² (area_km2)". The values sum to 1000. Empty bands below the lowest and above the highest glacierized band are left out. |
| `rgi6_links` | `list` | The overlaps with RGI 6.0 outlines from the corrected rgi6_links.csv file, one struct per overlap, empty when there is none. The file lists "all overlaps (greater than 200 m²) between pairs of RGI 7.0 and RGI 6.0 glacier outlines". Fields: rgi6_id, rgi7_reg, rgi6_reg, overlap_area_km2, rgi7_area_fraction (overlap divided by the RGI 7.0 area), rgi6_area_fraction (overlap divided by the RGI 6.0 area), cluster_id, n_rgi7 (RGI 7.0 outlines that overlap the RGI 6.0 outline) and n_rgi6 (RGI 6.0 outlines that overlap the RGI 7.0 outline). |
| `subm_n_outlines` | `uint32` | "Number of outlines from this submission used in RGI 7.0." From the submission_info.csv file of the glacier's first-order region, so it counts the outlines of that region. |
| `subm_anlys_time` | `timestamp[us]` | "Representative time the outline analysis was carried out." |
| `subm_release_dt` | `timestamp[us]` | "Date at which the submission was realeased on GLIMS." |
| `subm_proc_desc` | `string` | "Description of the processing done to create the glacier outlines." |
| `subm_chief_affl` | `string` | "Affiliation of the chief of the regional center or the person(s) who submitted the data." |
| `subm_submitters` | `string` | "Person(s) who submitted the data." |
| `subm_analysts` | `string` | "Person(s) who created the data." |
| `subm_rc_id` | `uint16` | "GLIMS ID for the regional center." |
| `geometry` | `binary` | Glacier geometry (Polygon) (deg) |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Coded columns

The codes and their meanings are from the
[RGI 7.0 user guide](https://rgidata.org/user_guide/).

### `primeclass`

| Value | Meaning |
| --- | --- |
| `0` | Miscellaneous |
| `1` | Continental ice sheet |
| `2` | Icefield |
| `3` | Ice cap |
| `4` | Outlet glacier |
| `5` | Valley glacier |
| `6` | Mountain glacier |
| `7` | Glacieret and snowfield |
| `8` | Ice shelf |
| `9` | Rock glacier |
| `10` | Undefined |

"It is currently poorly populated, with only few submissions to GLIMS having provided this information."

### `conn_lvl`

| Value | Meaning |
| --- | --- |
| `0` | No connection |
| `1` | Weak connection |

### `surge_type`

| Value | Meaning |
| --- | --- |
| `0` | No evidence |
| `1` | Possible |
| `2` | Probable |
| `3` | Observed |
| `9` | Not assigned |

### `term_type`

| Value | Meaning |
| --- | --- |
| `0` | Land-terminating |
| `1` | Marine-terminating |
| `2` | Lake-terminating |
| `3` | Shelf-terminating |
| `9` | Not assigned |

"All glaciers in RGI 7.0 have been assigned the "Not assigned" category, except for the marine-terminating". "As of RGI 7.0, no region or glacier has any attributes available for lake-terminating or shelf-terminating glaciers."

### `aspect_sec`

| Value | Meaning |
| --- | --- |
| `1` | North |
| `2` | North-east |
| `3` | East |
| `4` | South-east |
| `5` | South |
| `6` | South-west |
| `7` | West |
| `8` | North-west |
| `9` | Not assigned |

### `dem_source`

| Value | Meaning |
| --- | --- |
| `COPDEM30` | Copernicus DEM, 30 m |
| `COPDEM90` | Copernicus DEM, 90 m |
| `ASTER` | ASTER, an alternative product where the Copernicus DEM is not available |
| `DEM3` | DEM3, an alternative product where the Copernicus DEM is not available |
| `RAMP` | RAMP, an alternative product where the Copernicus DEM is not available |
| `TANDEM` | TANDEM, an alternative product where the Copernicus DEM is not available |

"The main DEM product used for RGI 7.0 is the Copernicus DEM". "For all glaciers which grid size is below 60 m we use the 30 m COP-DEM product as source, and use the 90 m COP-DEM product for all other glaciers."

## Citation

Cite the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

The user guide describes every file and attribute:

> Maussion, F., Hock, R., Paul, F., Raup, B., Rastner, P., Zemp, M., Andreassen, L., Barr, I., Bolch, T., Kochtitzky, W., McNabb, R., & Tielidze, L. (2023). *The Randolph Glacier Inventory version 7.0 user guide*. Zenodo. https://doi.org/10.5281/zenodo.8362857

This mirror asks for no citation of its own. You may add "accessed via
https://source.coop/lqgentner/rgi".

## License

[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). The RGI user guide states: "The
RGI may be used freely under the Creative Commons Attribution 4.0
International License with due acknowledgement (by proper referencing, see
below). Where appropriate (for example for regional studies), users are
invited to cite the analysts who provided the RGI outlines."

## Provenance

- The authoritative distribution is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7),
  https://doi.org/10.5067/F6JMOVY5NAVZ. It needs an Earthdata login.
- The build downloads the same release without a login from the RGI
  server of Fabien Maussion at the University of Bremen. Its four global zips are
  byte-identical to NSIDC's.
- The values are those of the RGI release. The build restructures the files
  and fixes documented upstream errors. Each fix, with counts and IDs, is in
  [docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md).
