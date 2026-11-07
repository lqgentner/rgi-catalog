# Changelog

Each entry is one mirror revision of the published catalog. A revision name
is the RGI version plus a counter, for example `7.0-r1`. The git tag carries
the same name.

## Unreleased

The default styles write each glacier name along a curved line near the
glacier's terminus. Before, a name was a straight label at RGI's point of
the glacier.

- The `tiles` step fits one label line per glacier and zoom, from z7 to z14.
  7,438 of the 9,457 named glaciers have a label line at one or more zooms.
- The text keeps 9.6 px to the glacier's outline on both sides of the line.
  On a narrow tongue the name moves up the glacier.
- The `glacier-labels` layer holds the label lines. The z12 tiles also hold
  the lines of z13 and z14, which MapLibre shows by overzoom.
- The new `glacier-label-points` layer holds RGI's point of each named
  glacier. No default style draws it.
- A style shows each label line from its `label_zoom` up to the next zoom. The
  filter also matches one line per glacier in a renderer that uses a
  fractional zoom, such as OpenLayers.
- The 2,019 named glaciers without a label line have no name in the styles.

The PMTiles archive is 1,144.5 MB. `docs/DESIGN.md` gives the method and the
measurements.

Two new rules change `display_name` for 451 glaciers. Two new overrides
change 2 more:

- A Swiss name that ends with a glacier word and a particle starts with them:
  `CHEILON GLACIER DE` becomes `Glacier de Cheilon`, and
  `MORTERATSCH VADRET DA` becomes `Vadret da Morteratsch`.
- In region 17, `Gl.` at the start of a name becomes `Glaciar`: `Gl. Viedma`
  becomes `Glaciar Viedma`.
- `Gl.` stays in the 36 names of South Georgia. The region has Spanish and
  English names, so the language of `Gl.` is not known.

`docs/PROVENANCE.md` lists every rule.

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
