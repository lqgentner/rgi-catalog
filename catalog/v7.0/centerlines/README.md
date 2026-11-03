# RGI 7.0 glacier centerlines

[Portolan/STAC browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/centerlines/collection.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/products/centerlines_product.html) · [Code on GitHub](https://github.com/lqgentner/rgi-catalog) · [Data on Source Cooperative](https://source.coop/lqgentner/rgi)

The GeoParquet file has one row per centerline. Each glacier has a main centerline and tributary centerlines, and each row has RGI's attributes. The collection also has a PMTiles archive for web maps.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## About the product

The RGI 7.0 user guide describes the
[glacier centerlines product](https://rgidata.org/user_guide/products/centerlines_product.html):

<!-- human-written -->

> The glacier centerlines product contains geometrical centerlines for the main branches and major tributaries of all glaciers in the RGI 7.0 glacier product. The centerlines are computed using a geometrical flow routing algorithm first described by Kienholz et al. [2014] and implemented and executed by the Open Global Glacier Model (OGGM) [Maussion et al., 2019].

<!-- /human-written -->

## Files

- [`rgi7.0-centerlines.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet): 367,724 rows, 210.3 MB. GeoParquet 2.0.0 in 90 row groups of up to 4,096 rows, zstd-compressed and ordered by `rgi_id`. Each row group contains a separate range of `rgi_id` values, so a filter on one value reads one row group. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the PMTiles web map archive from z0 to z12, with the layers `centerlines`. The tiles contain every column except the list and struct columns, which vector tiles cannot store: `bbox`. Fetch those from the GeoParquet file by `rgi_id`.
## Map styles

- [Centerlines](./styles/centerlines.json) (default): Glacier centerlines over the glacier outlines. The main centerlines are drawn wider and show from z8, the others from z9. A longer line shows from the first zoom at which it spans 32 pixels, from z4 on.
- [Glaciers](./styles/glaciers.json): Glacier outlines and names.

## Access

The file is public over HTTPS, so readers need no account. The data can be streamed directly without downloading. This geopandas code reads the main centerline of the Rhone glacier.
Install `geopandas`, `pyarrow`, `fsspec`, and `aiohttp`.

```python
import geopandas as gpd

gdf = gpd.read_parquet(
    "https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet",
    columns=["rgi_id", "rgi_g_id", "segment_id", "length_m", "geometry"],
    filters=[("rgi_g_id", "==", "RGI2000-v7.0-G-11-01706"), ("is_main", "==", True)],
)
```

This DuckDB query reads the same rows:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT rgi_id, rgi_g_id, segment_id, length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet'
WHERE rgi_g_id = 'RGI2000-v7.0-G-11-01706' AND is_main;
```

`centerlines/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/centerlines/rgi7.0-centerlines.parquet`.

## QGIS

> **Coming soon.** This mirror is not in the Portolan registry yet, so the
> plugin does not list its collections.

Install the [Portolan Registry plugin](https://github.com/portolan-sdi/portolan-registry-qgis).
Open it from the Web menu and select this collection.

- **View on map** adds the PMTiles web map with the collection's style.
- **Load full data** adds the GeoParquet file for an area of interest that you draw.

## Columns

| Column | Type | Description |
| --- | --- | --- |
| `rgi_id` | `string` | Unique identifier assigned to a centerline. |
| `rgi_g_id` | `string` | Glacier ID to which the centerline belongs. |
| `segment_id` | `uint8` | Integer number uniquely identifying this centerline within the glacier. The main centerline is always last. |
| `is_main` | `bool` | Integer number indicating whether the centerline is the main centerline (1) or not (0). There is only one main centerline per glacier. |
| `outflow_id` | `int8` | Each secondary centerline flows into another centerline. This identifier points to the `segment_id` into which this centerline flows. |
| `strahler_n` | `uint8` | Strahler number (hydrological order) of the centerline, from lowest (1, line without tributaries but with possible descendants) to highest (the main centerline). |
| `length_m` | `uint32` | Length of the centerline. Unit: m. |
| `geometry` | `binary` | Centerline geometry (LineString). Unit: degrees. |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Processing notes

The values in this collection are those of the RGI release.
[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
every fix.

## License and citation

RGI 7.0 is under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). Anyone may use
it with due acknowledgement. Cite the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

Read the [user guide](https://rgidata.org/user_guide/) for a detailed description of RGI 7.0:

> Maussion, F., Hock, R., Paul, F., Raup, B., Rastner, P., Zemp, M., Andreassen, L., Barr, I., Bolch, T., Kochtitzky, W., McNabb, R., & Tielidze, L. (2023). *The Randolph Glacier Inventory version 7.0 user guide*. Zenodo. https://doi.org/10.5281/zenodo.8362857

For this collection, the user guide also asks to cite the papers of the
method:

> Kienholz, C., Rich, J. L., Arendt, A. A., & Hock, R. (2014). A new method for deriving glacier centerlines applied to glaciers in Alaska and northwest Canada. *The Cryosphere, 8*(2), 503–519. https://doi.org/10.5194/tc-8-503-2014

> Maussion, F., Butenko, A., Champollion, N., Dusch, M., Eis, J., Fourteau, K., Gregor, P., Jarosch, A. H., Landmann, J., Oesterle, F., Recinos, B., Rothenpieler, T., Vlug, A., Wild, C. T., & Marzeion, B. (2019). The Open Global Glacier Model (OGGM) v1.1. *Geoscientific Model Development, 12*(3), 909–931. https://doi.org/10.5194/gmd-12-909-2019

For regional studies, the user guide also invites users to cite the analysts
who provided the outlines. The `subm_analysts` column of the glaciers names
them.

A citation of this mirror is optional. You may add "accessed via
https://source.coop/lqgentner/rgi".

## Provenance

NSIDC distributes the authoritative copy of the release,
[RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7) (https://doi.org/10.5067/F6JMOVY5NAVZ),
to users with an Earthdata login. The build downloads the same release from
[the RGI server at the University of Bremen](https://cluster.klima.uni-bremen.de/~fmaussion/misc/rgi7_data/),
which needs no login. Its four global zips are byte-identical to the zips at
NSIDC.
