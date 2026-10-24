# RGI 7.0

[Open in data browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/catalog.json) · [RGI 7.0 user guide](https://rgidata.org/user_guide/) · [Source repository](https://github.com/lqgentner/rgi-catalog) · [Report a problem](https://github.com/lqgentner/rgi-catalog/issues) · [Hosting repository](https://source.coop/lqgentner/rgi)

RGI 7.0, released in 2023. It holds 274,531 glacier outlines with their attributes. This is mirror revision
`7.0-r1`, built 2026-10-24.

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is [RGI 7.0 at NSIDC](https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium:

> RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center. https://doi.org/10.5067/F6JMOVY5NAVZ

## Collections

| Collection | Rows | GeoParquet | Guides |
| --- | ---: | ---: | --- |
| [glaciers](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/glaciers/collection.json) | 274,531 | 258.0 MB | [README](glaciers/README.md) · [Agents guide](glaciers/AGENTS.md) |
| [complexes](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/complexes/collection.json) | 192,869 | 213.3 MB | [README](complexes/README.md) · [Agents guide](complexes/AGENTS.md) |
| [intersects](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/intersects/collection.json) | 130,429 | 17.0 MB | [README](intersects/README.md) · [Agents guide](intersects/AGENTS.md) |
| [centerlines](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/centerlines/collection.json) | 367,724 | 211.0 MB | [README](centerlines/README.md) · [Agents guide](centerlines/AGENTS.md) |
| [regions](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/regions/collection.json) | 110 | 1.0 MB | [README](regions/README.md) · [Agents guide](regions/AGENTS.md) |

The web map archive `rgi7.0.pmtiles` (1043.8 MB) holds the layers `regions`, `region-labels`, `complexes`, `glaciers`, `glacier-labels`, `centerlines`, `intersects`, z0 to z12.

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
