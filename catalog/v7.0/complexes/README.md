# RGI 7.0 glacier complexes

[Open in data browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/complexes/collection.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/products/glacier_complex_product.html) · [Source repository](https://github.com/lqgentner/rgi-catalog) · [Report a problem](https://github.com/lqgentner/rgi-catalog/issues) · [Hosting repository](https://source.coop/lqgentner/rgi)

One row per glacier complex: the glaciers that touch, merged into one outline, with RGI's attributes and the IDs of the member glaciers, in one GeoParquet file. The web map archive holds the outlines.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## About the product

The RGI 7.0 user guide describes the
[glacier complex product](https://rgidata.org/user_guide/products/glacier_complex_product.html):

> The glacier complex product is the result of a spatial merge operation of the glacier product (dissolve in the GIS jargon). The operation is realized on geometries only, which means that any cluster of connected glaciers (however small the connection) will be merged into one entity in the glacier complex product. The resulting inventory has the same area but a smaller or equal number of entities as the glacier product. Only a few attributes from the original glacier product remain after the merge.

## Files

- [`rgi7.0-complexes.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet): 192,869 rows, 214.7 MB. GeoParquet 2.0.0 in 48 row groups of up to 4,096 rows, zstd-compressed and ordered by `rgi_id`. Each row group holds a separate range of `rgi_id` values, so a filter on one value reads one row group. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the web map archive (PMTiles, vector tiles, z0 to z12), with the layers `complexes`. Below z10 the layer is an overview. A feature that spans 3 pixels at a zoom is its simplified outline. A smaller feature is a point at RGI's `cenlon` and `cenlat`, one per grid cell of about a pixel, and the largest feature wins the cell. Overview features carry only `rgi_id`, `area_km2`. From z10 the tiles carry every column except the list and struct columns, which vector tiles cannot store: `glacier_ids`, `bbox`. Fetch those from the GeoParquet file by `rgi_id`.
## Map styles

- [Glacier complexes](./styles/complexes.json) (default): Glacier complexes: connected glaciers merged into one outline.
- [Glaciers](./styles/glaciers.json): Glacier outlines and names.

## Access

No account and no download are needed. This geopandas code reads the glacier complex of the Rhone glacier.
Install `geopandas`, `pyarrow`, `fsspec`, and `aiohttp`.

```python
import geopandas as gpd

gdf = gpd.read_parquet(
    "https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet",
    columns=["rgi_id", "area_km2", "glacier_ids", "geometry"],
    filters=[("rgi_id", "==", "RGI2000-v7.0-C-11-01208")],
)
gdf["n_glaciers"] = gdf.pop("glacier_ids").map(len)
```

This DuckDB query reads the same rows:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT rgi_id, area_km2, len(glacier_ids) AS n_glaciers
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet'
WHERE rgi_id = 'RGI2000-v7.0-C-11-01208';
```

`complexes/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/complexes/rgi7.0-complexes.parquet`.

## QGIS

Install the [Portolan Registry plugin](https://github.com/portolan-sdi/portolan-registry-qgis).
Open it from the Web menu and select this collection.

- **View on map** adds the PMTiles web map with the collection's style.
- **Load full data** adds the GeoParquet file for an area of interest that you draw.
  The plugin reads the file with DuckDB 1.5.0 or newer in the Python of QGIS.

## Columns

| Column | Type | Description |
| --- | --- | --- |
| `rgi_id` | `string` | Unique identifier assigned to a single glacier complex by the RGI |
| `o1region` | `string` | The code of the first-order region to which the glacier belongs. |
| `o2region` | `string` | The code of the second-order region to which the glacier belongs. |
| `cenlon` | `double` | Longitude of the representative point of the glacier complex, guaranteed to be located within the glacier outlines and approximatively central (not the centroid). (degrees) |
| `cenlat` | `double` | Latitude of the representative point of the glacier complex, guaranteed to be located within the glacier outlines and approximatively central (not the centroid). (degrees) |
| `utm_zone` | `uint8` | Number of the UTM zone for this glacier complex, based on its representative point. Note that this attribute is for information only, the geometries are all in WGS84. |
| `area_km2` | `double` | Area of the glacier complex. (km2) |
| `glacier_ids` | `list<element: string>` | The identifiers of the glaciers in the glacier complex, sorted (one or more depending on the size of the cluster). |
| `geometry` | `binary` | Glacier complex geometry (Polygon) (deg) |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Processing notes

The values are RGI's, except for these fixes of upstream errors.
[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
the IDs of the changed rows.

- `drop-z` in `geometry`, 192,869 rows: Dropped the Z coordinate, which is 0 in every vertex. See [rgi_issue_tracker#43](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/43).
- `polygon-validity` in `geometry`, 7 rows: Made the invalid outlines valid. Each repaired outline is one polygon. See [rgi_issue_tracker#48](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/48).

The build does not fix these known upstream issues:

- [rgi_issue_tracker#21](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/21): "Glacier complex product may have artifacts at glacier divides"

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
