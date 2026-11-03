# RGI 7.0 glacier intersects

[Portolan/STAC browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/intersects/collection.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/products/intersects_product.html) · [Code on GitHub](https://github.com/lqgentner/rgi-catalog) · [Data on Source Cooperative](https://source.coop/lqgentner/rgi)

The GeoParquet file has one row per intersect. An intersect is a line that divides two adjacent glaciers, and its row has the IDs of both glaciers. The collection also has a PMTiles archive for web maps.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## About the product

The RGI 7.0 user guide describes the
[glacier intersects product](https://rgidata.org/user_guide/products/intersects_product.html):

<!-- human-written -->

> The glacier intersects products includes only the “divides” or “borders” between adjacent glaciers rather than the complete outlines. The resulting geometries are single lines (each with their own id), with attributes rgi_g_id_1 and rgi_g_id_2 indicating which glacier entities are adjacent. This product is useful for describing the connection between two glaciers (for example by the length of a common boundary) or for glacier models able to use this kind of information.

<!-- /human-written -->

## Files

- [`rgi7.0-intersects.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet): 130,429 rows, 16.8 MB. GeoParquet 2.0.0 in 13 row groups of up to 10,240 rows, zstd-compressed and ordered by `rgi_id`. Each row group contains a separate range of `rgi_id` values, so a filter on one value reads one row group. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the PMTiles web map archive from z0 to z12, with the layers `intersects`. The tiles contain every column except the list and struct columns, which vector tiles cannot store: `bbox`. Fetch those from the GeoParquet file by `rgi_id`.
## Map styles

- [Intersects](./styles/intersects.json) (default): Glacier intersects over the glacier outlines. An intersect is a line that divides two adjacent glaciers. The intersects show from z9. A longer line shows from the first zoom at which it spans 32 pixels, from z4 on.
- [Glaciers](./styles/glaciers.json): Glacier outlines and names.

## Access

The file is public over HTTPS, so readers need no account. The data can be streamed directly without downloading. This geopandas code reads the intersects of the Rhone glacier.
Install `geopandas`, `pyarrow`, `fsspec`, and `aiohttp`.

```python
import geopandas as gpd

gdf = gpd.read_parquet(
    "https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet",
    columns=["rgi_id", "rgi_g_id_1", "rgi_g_id_2", "length_m", "geometry"],
    filters=[
        [("rgi_g_id_1", "==", "RGI2000-v7.0-G-11-01706")],
        [("rgi_g_id_2", "==", "RGI2000-v7.0-G-11-01706")],
    ],
)
```

This DuckDB query reads the same rows:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT rgi_id, rgi_g_id_1, rgi_g_id_2, length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet'
WHERE 'RGI2000-v7.0-G-11-01706' IN (rgi_g_id_1, rgi_g_id_2);
```

`intersects/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet`.

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
| `rgi_id` | `string` | Unique identifier assigned to an intersect. |
| `rgi_g_id_1` | `string` | Glacier ID of one side of the intersect (arbitrary). |
| `rgi_g_id_2` | `string` | Glacier ID of the other side of the intersect (arbitrary). |
| `length_m` | `double` | Length of the intersect. Unit: m. |
| `geometry` | `binary` | Intersect geometry (LineString). Unit: degrees. |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Processing notes

The values are RGI's, except for these fixes of upstream errors.
[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
the IDs of the changed rows.

- `drop-z` in `geometry`, 130,429 rows: The Z coordinate is dropped. It is 0 in every vertex. See [rgi_issue_tracker#43](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/43).

## License and citation

RGI 7.0 is under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). Anyone may use
it with due acknowledgement. Cite the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

Read the [user guide](https://rgidata.org/user_guide/) for a detailed description of RGI 7.0:

> Maussion, F., Hock, R., Paul, F., Raup, B., Rastner, P., Zemp, M., Andreassen, L., Barr, I., Bolch, T., Kochtitzky, W., McNabb, R., & Tielidze, L. (2023). *The Randolph Glacier Inventory version 7.0 user guide*. Zenodo. https://doi.org/10.5281/zenodo.8362857

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
