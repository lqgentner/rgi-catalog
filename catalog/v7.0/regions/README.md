# RGI 7.0 glacier regions

[Open in data browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/regions/collection.json) · [Source repository](https://github.com/lqgentner/rgi-catalog) · [Report a problem](https://github.com/lqgentner/rgi-catalog/issues) · [Hosting repository](https://source.coop/lqgentner/rgi)

The 20 first-order and 90 second-order glacier regions of RGI 7.0, in one GeoParquet file. Regions 10 and 19-15 cross the antimeridian and are two rows each. The web map archive holds the boundaries and the names.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Files

- [`rgi7.0-regions.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet): 112 rows, 1.0 MB. GeoParquet 2.0.0 in 1 row groups of up to 112 rows, zstd-compressed and ordered along a Hilbert curve. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the web map archive (PMTiles, vector tiles, z0 to z12), with the layers `regions`, `region-labels`. The tiles carry every column except the list and struct columns, which vector tiles cannot store: `bbox`. Fetch those from the GeoParquet file by `long_code`. Timestamps are strings in the tiles.

## Map styles

- [Glacier regions](./styles/regions.json) (default): First-order (orange) and second-order (purple) glacier regions, with their names.
- [Glaciers with names](./styles/full-map.json): Glacier outlines (blue) and centerlines (red), with glacier names and the boundaries and names of the glacier regions. Larger glaciers are named at lower zooms.

## Access

No account and no download are needed. This DuckDB query reads the first-order regions:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT o1region, full_name, long_code
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet'
WHERE level = 1;
```

`regions/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/regions/rgi7.0-regions.parquet`.

## Columns

| Column | Type | Description |
| --- | --- | --- |
| `level` | `uint8` | 1 for a first-order region, 2 for a second-order region. RGI ships the two levels as two shapefiles. This file holds both, one row per polygon. |
| `o1region` | `string` | The code of the first-order region. "The RGI_CODE column is now called o1region (first order files) and o2region (second-order files)." |
| `o2region` | `string` | The code of the second-order region. Null for a first-order region. |
| `full_name` | `string` | The region name. "All abbreviations in the second-order regions file have been replaced by their full name." |
| `long_code` | `string` | The code and the name in one text. "This field is used to name the corresponding RGI shapefiles." |
| `geometry` | `binary` | The region outline, a polygon in EPSG:4326. Regions 10 and 19-15 are split at the antimeridian into an eastern and a western row. |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Citation

Cite the source of this collection:

> World Glacier Monitoring Service. (2023). *GTN-G glacier regions (GlacReg)* [Data set]. Global Terrestrial Network for Glaciers. https://doi.org/10.5904/gtng-glacreg-2023-07

It is part of the RGI 7.0 release. Cite the RGI Consortium as well:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

The user guide describes every file and attribute:

> Maussion, F., Hock, R., Paul, F., Raup, B., Rastner, P., Zemp, M., Andreassen, L., Barr, I., Bolch, T., Kochtitzky, W., McNabb, R., & Tielidze, L. (2023). *The Randolph Glacier Inventory version 7.0 user guide*. Zenodo. https://doi.org/10.5281/zenodo.8362857

This mirror asks for no citation of its own. You may add "accessed via
https://source.coop/lqgentner/rgi".

## License

The regions are those of the Global Terrestrial Network for Glaciers. Their
DataCite record states the terms as: "Open access for scientific and
educational purposes under requirement of correct citation". See
[GTN-G Glacier Regions](https://www.gtn-g.ch/glacreg/).

The rest of the RGI 7.0 release is under
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
