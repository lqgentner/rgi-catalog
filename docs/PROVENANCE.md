# Provenance

This file records where the mirror's bytes come from, and every change the
build makes to RGI's values. The mirror is unofficial. It is not endorsed by
the RGI Consortium.

## Source verification

The build downloads RGI 7.0 from Fabien Maussion's server at the University of
Bremen
(`https://cluster.klima.uni-bremen.de/~fmaussion/misc/rgi7_data/`). That
server holds the same release tree as NSIDC (`nsidc0770_rgi_v7`,
doi:10.5067/f6jmovy5navz), without a login. `metadata/sources.yaml` pins each
input by URL, sha256 and size. The build refuses a file that does not match.

On 2026-10-22 the four global zips from Bremen were compared with copies
downloaded from NSIDC through Earthdata. All four are byte-identical.

| File | NSIDC sha256 | Bremen sha256 | Equal |
| --- | --- | --- | --- |
| `RGI2000-v7.0-G-global.zip` | `33573533f17de6f1b39bafc807002cdda44a150bb8ed94329387de11751b8a85` | `33573533f17de6f1b39bafc807002cdda44a150bb8ed94329387de11751b8a85` | yes |
| `RGI2000-v7.0-C-global.zip` | `2c312585097ec1c11350f4abaa050d8574b36acd5bbcbd1d1fe5024abdb0d026` | `2c312585097ec1c11350f4abaa050d8574b36acd5bbcbd1d1fe5024abdb0d026` | yes |
| `RGI2000-v7.0-I-global.zip` | `9a002a5b2cdffcf07893f5d446321ace4ed2c16f8400ff5fd9d5143887d27690` | `9a002a5b2cdffcf07893f5d446321ace4ed2c16f8400ff5fd9d5143887d27690` | yes |
| `RGI2000-v7.0-L-global.zip` | `6929554c360f6b68a5fdd4ea97879108b094d5a4913abb54d1d8506fb864ba23` | `6929554c360f6b68a5fdd4ea97879108b094d5a4913abb54d1d8506fb864ba23` | yes |

Two inputs have no NSIDC counterpart to compare with:

- `RGI2000-v7.0-regions.zip` comes from the same Bremen release tree.
- `RGI2000-v7.0-G-global-rgi6_links.csv` holds the corrected RGI 6 links
  (GLIMS-RGI/rgi_issue_tracker#41). NSIDC ships the uncorrected links.
