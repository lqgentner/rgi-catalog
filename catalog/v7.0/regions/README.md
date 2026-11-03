# RGI 7.0 glacier regions

[Portolan/STAC browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/regions/collection.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/02_regions_definition.html) · [Code on GitHub](https://github.com/lqgentner/rgi-catalog) · [Data on Source Cooperative](https://source.coop/lqgentner/rgi)

The 20 first-order and 90 second-order glacier regions of RGI 7.0, in one GeoParquet file, one row per region. The collection also has a PMTiles archive for web maps.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## About the product

The RGI 7.0 user guide describes the
[rgi glacier regions](https://rgidata.org/user_guide/02_regions_definition.html):

<!-- human-written -->

> RGI outlines are organized into 20 first-order glacier regions. This is one more than in RGI 6.0 and earlier versions, since former region 19 was split into two regions (global map; Table 1a). These are further subdivided into second-order regions, of which there are 90 in total in RGI 7.0 (Table 1b). Glacier regions are useful for regional assessments of glacier change and other variables.

<!-- /human-written -->

## Files

- [`rgi7.0-regions.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet): 110 rows, 1.0 MB. GeoParquet 2.0.0 in 1 row groups of up to 110 rows, zstd-compressed and ordered along a Hilbert curve. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the PMTiles web map archive from z0 to z12, with the layers `regions`, `region-boundaries`, `region-labels`. The tiles contain every column except the list and struct columns, which vector tiles cannot store: `bbox`. Fetch those from the GeoParquet file by `long_code`.
## Map styles

- [Glacier regions](./styles/regions.json) (default): First-order and second-order glacier regions, with their names.
- [Glaciers](./styles/glaciers.json): Glacier outlines and names.

## Access

The file is public over HTTPS, so readers need no account. The data can be streamed directly without downloading. This geopandas code reads the first-order regions.
Install `geopandas`, `pyarrow`, `fsspec`, and `aiohttp`.

```python
import geopandas as gpd

gdf = gpd.read_parquet(
    "https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet",
    columns=["o1region", "full_name", "long_code", "geometry"],
    filters=[("level", "==", 1)],
)
```

This DuckDB query reads the same rows:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT o1region, full_name, long_code
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet'
WHERE level = 1;
```

`regions/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet`.

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
| `level` | `uint8` | 1 for a first-order region, 2 for a second-order region. RGI distributes the two levels as two shapefiles. This file contains both, one row per polygon. |
| `o1region` | `string` | The code of the first-order region. |
| `o2region` | `string` | The code of the second-order region. Null for a first-order region. |
| `full_name` | `string` | The full name of the region, without abbreviations. |
| `long_code` | `string` | The code and the name of the region in one text. RGI uses it to name the region files. |
| `geometry` | `binary` | The region outline in EPSG:4326. Regions 10 and 19-15 cross the antimeridian. Each is a MultiPolygon of an eastern and a western part. |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Processing notes

The values in this collection are those of the RGI release.
[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
every fix.

## License and citation

The glacier regions come from the Global Terrestrial Network for Glaciers
(GTN-G). Their DataCite record states the terms as: "Open access for
scientific and educational purposes under requirement of correct citation".
See [GTN-G Glacier Regions](https://www.gtn-g.ch/glacreg/).
Cite the source of this collection:

> World Glacier Monitoring Service. (2023). *GTN-G glacier regions (GlacReg)* [Data set]. Global Terrestrial Network for Glaciers. https://doi.org/10.5904/gtng-glacreg-2023-07

The rest of the RGI 7.0 release is under
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). The regions are part of the
release, so cite the RGI Consortium as well:

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
