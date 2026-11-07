# RGI 7.0

[Portolan/STAC browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/catalog.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/) · [Code on GitHub](https://github.com/lqgentner/rgi-catalog) · [Data on Source Cooperative](https://source.coop/lqgentner/rgi)

RGI 7.0, released in 2023. It holds 274,531 glacier outlines with their attributes. This is mirror revision
`7.0-r2`, built 2026-11-07.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

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
- `CHEILON GLACIER DE` becomes `Glacier de Cheilon`.

[docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md) lists
every changed row and the rules of `display_name`.

## Collections

| Collection | Rows | GeoParquet | Guides |
| --- | ---: | ---: | --- |
| [glaciers](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/glaciers/collection.json) | 274,531 | 261.4 MB | [README](glaciers/README.md) · [Agents guide](glaciers/AGENTS.md) |
| [complexes](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/complexes/collection.json) | 192,869 | 214.7 MB | [README](complexes/README.md) · [Agents guide](complexes/AGENTS.md) |
| [intersects](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/intersects/collection.json) | 130,429 | 16.8 MB | [README](intersects/README.md) · [Agents guide](intersects/AGENTS.md) |
| [centerlines](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/centerlines/collection.json) | 367,724 | 210.3 MB | [README](centerlines/README.md) · [Agents guide](centerlines/AGENTS.md) |
| [regions](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/regions/collection.json) | 110 | 1.0 MB | [README](regions/README.md) · [Agents guide](regions/AGENTS.md) |

The web map archive `rgi7.0.pmtiles` (1144.5 MB) holds the layers `regions`, `region-boundaries`, `region-labels`, `complexes`, `glaciers`, `glacier-labels`, `glacier-label-points`, `centerlines`, `intersects`, z0 to z12.

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
