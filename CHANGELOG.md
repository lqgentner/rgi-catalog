# Changelog

Each entry is one mirror revision of the published catalog. A revision name
is the RGI version plus a counter, for example `7.0-r1`. The git tag carries
the same name.

## Unreleased

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
