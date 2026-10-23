# RGI 7.0 glacier intersects

[Open in data browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/intersects/collection.json) · [Source repository](https://github.com/lqgentner/rgi-catalog) · [Report a problem](https://github.com/lqgentner/rgi-catalog/issues) · [Hosting repository](https://source.coop/lqgentner/rgi)

One row per intersect: a line that divides two adjacent glaciers, with the IDs of both glaciers, in one GeoParquet file. The web map archive holds the lines from z10.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Files

- [`rgi7.0-intersects.parquet`](https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet): 130,429 rows, 17.0 MB. GeoParquet 2.0.0 in 13 row groups of up to 10,240 rows, zstd-compressed and ordered along a Hilbert curve. A `bbox` column lets readers skip row groups in a spatial filter.
- [`rgi7.0.pmtiles`](https://data.source.coop/lqgentner/rgi/v7.0/rgi7.0.pmtiles): the web map archive (PMTiles, vector tiles, z0 to z12), with the layers `intersects`. The tiles carry every column except the list and struct columns, which vector tiles cannot store: `bbox`. Fetch those from the GeoParquet file by `rgi_id`.
## Map styles

- [Intersects](./styles/intersects.json) (default): Intersects (black): the divides between adjacent glaciers, from z10, over the glacier outlines (pale blue).
- [Reference map](./styles/reference.json): Glacier outlines (blue) and centerlines (red), with glacier names and the boundaries and names of the glacier regions. Larger glaciers are named at lower zooms.

## Access

No account and no download are needed. This DuckDB query reads the intersects of the Rhone glacier:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT rgi_id, rgi_g_id_1, rgi_g_id_2, length_m
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet'
WHERE 'RGI2000-v7.0-G-11-01706' IN (rgi_g_id_1, rgi_g_id_2);
```

`intersects/AGENTS.md` has more recipes. Each file is also readable over
anonymous S3 at `s3://us-west-2.opendata.source.coop/lqgentner/rgi/v7.0/intersects/rgi7.0-intersects.parquet`.

## Columns

| Column | Type | Description |
| --- | --- | --- |
| `rgi_id` | `string` | Unique identifier assigned to a single intersect line by the RGI |
| `rgi_g_id_1` | `string` | Glacier ID of one side of the intersect (arbitrary) |
| `rgi_g_id_2` | `string` | Glacier ID of the other side of the intersect (arbitrary) |
| `length_m` | `double` | Length of the intersect in meters (m) |
| `geometry` | `binary` | Intersect geometry (LineString) (deg) |
| `bbox` | `struct` | The bounding box of the geometry (xmin, ymin, xmax, ymax), the GeoParquet covering column. Readers use it to skip row groups in a spatial filter. |

## Processing notes

The values are RGI's, except for these fixes of upstream errors.
[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
the IDs of the changed rows.

- `drop-z` in `geometry`, 130,429 rows: Dropped the Z coordinate, which is 0 in every vertex. See [rgi_issue_tracker#43](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/43).

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
