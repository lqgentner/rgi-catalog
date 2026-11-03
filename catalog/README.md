<!-- vale Portolan-Mechanics.Headings = NO -->
# Randolph Glacier Inventory Mirror
<!-- vale Portolan-Mechanics.Headings = YES -->

[Portolan/STAC browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/catalog.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/) · [Code on GitHub](https://github.com/lqgentner/rgi-catalog) · [Data on Source Cooperative](https://source.coop/lqgentner/rgi)

The Randolph Glacier Inventory (RGI) is a globally complete inventory of glacier outlines. This catalog republishes it as GeoParquet files and a web map archive. The values are those of the RGI release. Fixes of documented upstream errors are listed in the provenance record.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Files

- **GeoParquet, for analysis.** Each product is one GeoParquet file with all
  of its rows and columns. The side files of RGI's glacier product are
  columns of the glaciers file: the hypsometry, the submission information,
  the glacier complex of each glacier and the links to RGI 6.0.
- **PMTiles, for web maps only.** One archive contains the vector tiles of
  all collections, with overviews for rendering at low zooms. Each
  collection provides a map style (`styles/*.json`). The tiles leave out the
  columns that vector tiles cannot store (`hypso_permille`, `rgi6_links`, `bbox` and `glacier_ids`). Read those from the
  GeoParquet files instead.

## Changes to RGI

The mirror keeps RGI's values, apart from these fixes of documented upstream
errors:

- Encoding errors in the text are repaired, so `AbbÃ© Glacier` becomes `Abbé Glacier`.
- The Z coordinate is dropped. It is 0 in every vertex. See [rgi_issue_tracker#43](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/43).
- Invalid outlines are made valid. Each repaired outline is still one polygon. See [rgi_issue_tracker#48](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/48).
- `rgi6_links` comes from the corrected links file, not from the links in the glacier product zip. See [rgi_issue_tracker#41](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/41).

The glaciers have one new column, `display_name`. It contains the names of
`glac_name`, cleaned for map labels. `glac_name` is unchanged, apart from the
encoding repair. The rules recase names in capitals, remove inventory codes,
and set placeholders to null:

- `FIESCHERGLETSCHER VS` becomes `Fieschergletscher VS`.
- `CN5J319J0001 Nianbaoyeze Glacier` becomes `Nianbaoyeze Glacier`.
- `S/N` becomes null.

[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
every changed row and the rules of `display_name`.

## Versions

- [RGI 7.0](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/catalog.json), mirror
  revision `7.0-r1`: the glaciers, complexes, intersects, centerlines and regions.
  Read the [README](v7.0/README.md) or the
  [agents guide](v7.0/AGENTS.md).

## Access

Every file is public over HTTPS and S3, so readers need no account. Install
`geopandas`, `pyarrow`, `fsspec`, and `aiohttp`. This geopandas code reads the
glaciers in a box. The `bbox` argument filters on the bbox column:

```python
import geopandas as gpd

alps = gpd.read_parquet(
    "https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet",
    columns=["rgi_id", "display_name", "area_km2", "geometry"],
    bbox=(6, 45.5, 11, 47.5),
)
```

This DuckDB query counts the glaciers of each first-order region without a
download:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT o1region, count(*) AS glaciers, round(sum(area_km2)) AS area_km2
FROM 'https://data.source.coop/lqgentner/rgi/v7.0/glaciers/rgi7.0-glaciers.parquet'
GROUP BY o1region
ORDER BY o1region;
```

## QGIS

> **Coming soon.** This mirror is not in the Portolan registry yet, so the
> plugin does not list its collections.

Install the [Portolan Registry plugin](https://github.com/portolan-sdi/portolan-registry-qgis).
Open it from the Web menu and select a collection.

- **View on map** adds the PMTiles web map with the collection's style. Use it to look at the glaciers at any zoom.
- **Load full data** adds the GeoParquet file for an area of interest that you draw. Use it for analysis.

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
