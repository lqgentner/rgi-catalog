# Changelog

Each entry is one mirror revision of the published catalog. A revision name
is the RGI version plus a counter, for example `7.0-r1`. The git tag carries
the same name.

## 7.0-r2 (2026-11-07)

The map writes each glacier name along the glacier, 510 display names read
more like the names on a map, and a small names table serves search.

### Added

- The default styles write each name along a curved line near the
  glacier's terminus, from z7 to z14. 7,438 of the 9,457 named glaciers have
  a label line.
- The `glacier-label-points` layer holds RGI's point of each named glacier.
- The glaciers collection has a names table,
  `rgi7.0-glacier-names.parquet`. It holds the ID, names and region codes of
  each glacier in 0.2 MB, in the row order of the glaciers file.

### Changed

- The `glacier-labels` layer holds label lines instead of points. A custom
  style needs `"symbol-placement": "line"` and a filter on `label_zoom`. The
  default styles show the filter.
- The 2,019 named glaciers without a label line have no name on the map.

### Fixed

- `display_name` expands more abbreviations to `Glacier` or `Glaciar`:
  `Gl. Viedma` becomes `Glaciar Viedma`.
- `display_name` puts inverted names back in their usual order:
  `CHEILON GLACIER DE` becomes `Glacier de Cheilon`.

`docs/DESIGN.md` gives the label method. `docs/PROVENANCE.md` lists every
name rule.

## 7.0-r1 (2026-11-03)

The first publication of the mirror, at <https://source.coop/lqgentner/rgi>.
It republishes the five RGI 7.0 products as GeoParquet files and one
PMTiles web map archive.

The values are those of the RGI 7.0 release. The build changes a value only
to fix one of these documented upstream errors:

- Encoding errors in `glac_name` are repaired.
- The Z coordinate, which is 0 in every vertex, is dropped
  (GLIMS-RGI/rgi_issue_tracker#43).
- Invalid outlines are made valid (GLIMS-RGI/rgi_issue_tracker#48).
- `rgi6_links` comes from the corrected links file
  (GLIMS-RGI/rgi_issue_tracker#41).

`docs/PROVENANCE.md` lists every changed row.

The glaciers have one new column, `display_name`, which holds the glacier
names of `glac_name`, cleaned for map labels. For example:

- Names in capitals are re-cased: `FIESCHERGLETSCHER VS` becomes
  `Fieschergletscher VS`.
- Inventory codes are removed: `CN5J319J0001 Nianbaoyeze Glacier` becomes
  `Nianbaoyeze Glacier`.
- Placeholders such as `S/N`, `Unnamed` and names that are only digits
  become null.

It adds to the RGI columns and does not replace `glac_name`.
