# RGI 7.0 (unofficial mirror)

[Open in data browser](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/catalog.json) · [Source repository](https://github.com/lqgentner/rgi-catalog) · [Report a problem](https://github.com/lqgentner/rgi-catalog/issues) · [Hosting repository](https://source.coop/lqgentner/rgi)

This is an unofficial mirror, not endorsed by the RGI Consortium. The authoritative source is RGI at NSIDC (https://nsidc.org/data/nsidc-0770/versions/7). Citation and credit belong to the RGI Consortium: RGI 7.0 Consortium, 2023. Randolph Glacier Inventory - A Dataset of Global Glacier Outlines, Version 7.0. Boulder, Colorado USA. NSIDC: National Snow and Ice Data Center. doi:10.5067/f6jmovy5navz.

RGI 7.0, released in 2023. It holds 274,531 glacier outlines with their attributes. This is mirror revision
`7.0-r1`, built 2026-10-22.

## Collections

| Collection | Rows | GeoParquet | Documentation |
| --- | ---: | ---: | --- |
| [glaciers](https://browser.portolan-sdi.org/#/external/data.source.coop/lqgentner/rgi/v7.0/glaciers/collection.json) | 274,531 | 258.0 MB | [README](glaciers/README.md) · [AGENTS](glaciers/AGENTS.md) |

The web map archive `glaciers/rgi7.0.pmtiles` (759.0 MB) holds the layers `glaciers`, `glacier-labels`, z0 to z12.

## Citation

Cite the RGI Consortium:

> RGI 7.0 Consortium, 2023. Randolph Glacier Inventory - A Dataset of Global Glacier Outlines, Version 7.0. Boulder, Colorado USA. NSIDC: National Snow and Ice Data Center. doi:10.5067/f6jmovy5navz.

The user guide describes every file and attribute:

> Maussion, F., Hock, R., Paul, F., Raup, B., Rastner, P., Zemp, M., Andreassen, L., Barr, I., Bolch, T., Kochtitzky, W., McNabb, R., and Tielidze, L. (2023). The Randolph Glacier Inventory version 7.0 User guide. Zenodo. https://doi.org/10.5281/zenodo.8362857

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
  doi:10.5067/f6jmovy5navz. It needs an Earthdata login.
- The build downloads the same release without a login from the RGI
  server of Fabien Maussion at the University of Bremen. Its four global zips are
  byte-identical to NSIDC's.
- The values are those of the RGI release. The build restructures the files
  and fixes documented upstream errors. Each fix, with counts and IDs, is in
  [docs/PROVENANCE.md](https://github.com/lqgentner/rgi-catalog/blob/main/docs/PROVENANCE.md).
