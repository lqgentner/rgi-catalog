# Provenance

This file records where the mirror's bytes come from, and every change the
build makes to RGI's values. The RGI Consortium has not endorsed
this unofficial mirror.

## Source verification

The build downloads RGI 7.0 from Fabien Maussion's server at the University of
Bremen
(`https://cluster.klima.uni-bremen.de/~fmaussion/misc/rgi7_data/`). That
server has the same release tree as NSIDC (`nsidc0770_rgi_v7`,
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

These inputs have no NSIDC counterpart to compare with:

- `RGI2000-v7.0-regions.zip` comes from the same Bremen release tree.
- `RGI2000-v7.0-G-global-rgi6_links.csv` holds the corrected RGI 6 links
  (GLIMS-RGI/rgi_issue_tracker#41). NSIDC distributes the uncorrected links.

## Changes to the release

The values are those of the RGI release. The build changes the layout of
the files, fixes the documented upstream errors listed below, and adds one
derived column, `display_name`. It keeps the other values as RGI publishes
them. `area_km2` and the
other computed attributes are kept as published, never recomputed.

The layout changes:

- Attributes come from the `-attributes.csv` files and outlines from the
  shapefiles, joined on `rgi_id`. The build fails if the two ID sets differ,
  or if a float in the `.dbf` differs from the CSV by more than 1e-12.
- The per-region files of a product become one GeoParquet file.
- The side files of the glacier product become columns of the glaciers
  file: the hypsometry (`hypso_z0_m`, `hypso_permille`), the submission
  information (`subm_*`), the complex links (`complex_id`) and the RGI 6.0
  links (`rgi6_links`). The complex links of the complex product become
  `glacier_ids`. A glacier with no entry in a side file keeps its row.
- RGI splits regions 10 and 19-15 at the antimeridian into two polygons.
  Each pair becomes one row with a MultiPolygon of both parts. The
  coordinates do not change.
- Integers are narrowed to a smaller type only when every value round-trips.
  Floats stay float64.
- The build skips the `.ipynb_checkpoints/` folders
  ([rgi_issue_tracker#42](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/42))
  and the per-region `README.md` files
  ([rgi_issue_tracker#49](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/49))
  of the global zips.

## Fixes

The convert step computes these counts and writes them to
`staging/v7.0/.reports/fixes.json`. The build record
`metadata/builds/v7.0.json` keeps them, and each collection README states
them. A test checks this table against the build record.

| Collection | Fix | Column | Rows changed |
| --- | --- | --- | ---: |
| glaciers | `text-encoding` | `glac_name` | 328 |
| glaciers | `drop-z` | `geometry` | 274,531 |
| glaciers | `polygon-validity` | `geometry` | 0 |
| complexes | `drop-z` | `geometry` | 192,869 |
| complexes | `polygon-validity` | `geometry` | 7 |
| intersects | `drop-z` | `geometry` | 130,429 |
| centerlines | `drop-z` | `geometry` | 0 |
| regions | `drop-z` | `geometry` | 0 |
| regions | `polygon-validity` | `geometry` | 0 |

<!-- vale Portolan-Mechanics.Headings = NO -->
### `drop-z`: the Z coordinate
<!-- vale Portolan-Mechanics.Headings = YES -->

The glacier, complex and intersect shapefiles store 3D geometries
([rgi_issue_tracker#43](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/43)).
Z is 0 in every vertex. The build drops it and fails on a non-zero Z. The
centerline and region shapefiles are 2D.

### `polygon-validity`: invalid outlines

[rgi_issue_tracker#48](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/48)
reports 6 invalid geometries: "3 in region 13, 1 in region 14, 15, 18". The
build checks every outline of the glaciers, complexes and regions with
shapely 2.2.0 (GEOS 3.14.1).

- All glacier outlines and region outlines are valid.
- 7 complex outlines are invalid. Each is a MultiPolygon with a second part
  of less than 2e-18 square degrees inside the first part (GEOS: "Nested
  shells"). `shapely.make_valid` drops that part. Each repaired outline is
  one Polygon, and its area differs by less than 1e-15 square degrees.

The repaired complexes:

| RGI ID |
| --- |
| `RGI2000-v7.0-C-01-06260` |
| `RGI2000-v7.0-C-13-29773` |
| `RGI2000-v7.0-C-13-39954` |
| `RGI2000-v7.0-C-13-53377` |
| `RGI2000-v7.0-C-14-16384` |
| `RGI2000-v7.0-C-15-05787` |
| `RGI2000-v7.0-C-18-01642` |

The build fails if a repair gives anything other than one valid Polygon.

### `text-encoding`: encoding errors

Some GLIMS submissions stored text with one of two encoding errors:

- UTF-8 bytes read as Latin-1: `AbbÃ© Glacier` for `Abbé Glacier`. This
  affects 183 names in regions 03 (1), 08 (95), 10 (22) and 12 (65).
- DOS code page 437 bytes read as Latin-1: `Mont V\x82lan` for `Mont Vélan`.
  This affects 145 names in region 11.

The build first decodes the text as UTF-8 from its Latin-1 bytes. If that
fails and the text holds a C1 control character (U+0080 to U+009F), it
decodes the bytes as code page 437. Otherwise the text is unchanged. The
repair runs on every text column of every product except the identifiers.
Only `glac_name` changes. The table shows RGI's value with each C1 control
character written as `\xNN`.

<details>
<summary>The 328 repaired names</summary>

| RGI ID | RGI's `glac_name` | Repaired |
| --- | --- | --- |
| `RGI2000-v7.0-G-03-01810` | `AbbÃ© Glacier` | Abbé Glacier |
| `RGI2000-v7.0-G-08-00122` | `BessedÃ¸rbreen` | Bessedørbreen |
| `RGI2000-v7.0-G-08-00224` | `SkjelÃ¥tindbreen` | Skjelåtindbreen |
| `RGI2000-v7.0-G-08-00284` | `LeirÃ¥bre` | Leiråbre |
| `RGI2000-v7.0-G-08-00287` | `SkjellÃ¥fonna` | Skjellåfonna |
| `RGI2000-v7.0-G-08-00293` | `TverrÃ¥dalsfonna` | Tverrådalsfonna |
| `RGI2000-v7.0-G-08-00296` | `JervÃ¥fonna` | Jervåfonna |
| `RGI2000-v7.0-G-08-00305` | `RÃ¸nnÃ¥fonna` | Rønnåfonna |
| `RGI2000-v7.0-G-08-00410` | `KjÃ¸lbreen` | Kjølbreen |
| `RGI2000-v7.0-G-08-00411` | `Storglombreen sÃ¸r` | Storglombreen sør |
| `RGI2000-v7.0-G-08-00592` | `SkrÃ¥isen` | Skråisen |
| `RGI2000-v7.0-G-08-00915` | `SkÃ¥risen` | Skårisen |
| `RGI2000-v7.0-G-08-01036` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-01163` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-01204` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-01214` | `GjÃ¸mmerdalsbreen` | Gjømmerdalsbreen |
| `RGI2000-v7.0-G-08-01252` | `RÃ¸dbergdalsbreen` | Rødbergdalsbreen |
| `RGI2000-v7.0-G-08-01264` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-01336` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-01402` | `GammvikblÃ¥isen` | Gammvikblåisen |
| `RGI2000-v7.0-G-08-01408` | `StefjellblÃ¥isen` | Stefjellblåisen |
| `RGI2000-v7.0-G-08-01409` | `Vestre VaggasblÃ¥isen` | Vestre Vaggasblåisen |
| `RGI2000-v7.0-G-08-01412` | `ReindalsblÃ¥isen` | Reindalsblåisen |
| `RGI2000-v7.0-G-08-01450` | `StÃ¸velbreen` | Støvelbreen |
| `RGI2000-v7.0-G-08-01455` | `Austre VaggasblÃ¥isen` | Austre Vaggasblåisen |
| `RGI2000-v7.0-G-08-01510` | `IsdaljÃ¸kelen` | Isdaljøkelen |
| `RGI2000-v7.0-G-08-01523` | `IsfjordjÃ¸kelen` | Isfjordjøkelen |
| `RGI2000-v7.0-G-08-01556` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-01576` | `LikkÃ¡jiehkki` | Likkájiehkki |
| `RGI2000-v7.0-G-08-01748` | `BlÃ¥skavlen` | Blåskavlen |
| `RGI2000-v7.0-G-08-01882` | `SÃ¸rsendalsbreen` | Sørsendalsbreen |
| `RGI2000-v7.0-G-08-01900` | `HÃ¸galmebreen` | Høgalmebreen |
| `RGI2000-v7.0-G-08-01922` | `HÃ¥skredskavlen` | Håskredskavlen |
| `RGI2000-v7.0-G-08-01936` | `Ã\x85rnesbreen` | Årnesbreen |
| `RGI2000-v7.0-G-08-01951` | `TjÃ¸tabreen` | Tjøtabreen |
| `RGI2000-v7.0-G-08-01984` | `LiastÃ¸lbreen` | Liastølbreen |
| `RGI2000-v7.0-G-08-01991` | `BÃ¸dalsbreen` | Bødalsbreen |
| `RGI2000-v7.0-G-08-02058` | `SkÃ¥lebreen` | Skålebreen |
| `RGI2000-v7.0-G-08-02065` | `FÃ¥bergstÃ¸lsbreen` | Fåbergstølsbreen |
| `RGI2000-v7.0-G-08-02085` | `HolÃ¥breen` | Holåbreen |
| `RGI2000-v7.0-G-08-02111` | `FannarÃ¥kbreen` | Fannaråkbreen |
| `RGI2000-v7.0-G-08-02125` | `SkagastÃ¸lsbreen` | Skagastølsbreen |
| `RGI2000-v7.0-G-08-02144` | `StÃ¸lsmaradalsbreen` | Stølsmaradalsbreen |
| `RGI2000-v7.0-G-08-02153` | `SnÃ¸ggeken` | Snøggeken |
| `RGI2000-v7.0-G-08-02186` | `SÃ¥ta` | Såta |
| `RGI2000-v7.0-G-08-02203` | `StÃ¸lsbotnbreen` | Stølsbotnbreen |
| `RGI2000-v7.0-G-08-02209` | `NystÃ¸lsbreen` | Nystølsbreen |
| `RGI2000-v7.0-G-08-02216` | `BÃ¸yabreen` | Bøyabreen |
| `RGI2000-v7.0-G-08-02273` | `BjÃ¸rnabreen` | Bjørnabreen |
| `RGI2000-v7.0-G-08-02284` | `BjÃ¥stadbreen` | Bjåstadbreen |
| `RGI2000-v7.0-G-08-02314` | `BjÃ¸rnakyrkjebreen` | Bjørnakyrkjebreen |
| `RGI2000-v7.0-G-08-02432` | `BlÃ¥breen` | Blåbreen |
| `RGI2000-v7.0-G-08-02452` | `BlÃ¥breen` | Blåbreen |
| `RGI2000-v7.0-G-08-02454` | `LjÃ¸sabreen` | Ljøsabreen |
| `RGI2000-v7.0-G-08-02742` | `BlikskÃ¥rbreen` | Blikskårbreen |
| `RGI2000-v7.0-G-08-02754` | `MidthÃ¸breen` | Midthøbreen |
| `RGI2000-v7.0-G-08-02773` | `StorlÃ¸ypbreen` | Storløypbreen |
| `RGI2000-v7.0-G-08-02823` | `Ã\x98yaskavlen` | Øyaskavlen |
| `RGI2000-v7.0-G-08-02894` | `RembesdalskÃ¥ka` | Rembesdalskåka |
| `RGI2000-v7.0-G-08-02896` | `Vestra LeirebottsskÃ¥ka` | Vestra Leirebottsskåka |
| `RGI2000-v7.0-G-08-02912` | `SÃ¥taskavlen` | Såtaskavlen |
| `RGI2000-v7.0-G-08-02916` | `Ã\x98ykjafonn` | Øykjafonn |
| `RGI2000-v7.0-G-08-02920` | `BlÃ¥skavlen` | Blåskavlen |
| `RGI2000-v7.0-G-08-03010` | `MÃ¸sevassbrea` | Møsevassbrea |
| `RGI2000-v7.0-G-08-03013` | `BlomstÃ¸lskardsbreen` | Blomstølskardsbreen |
| `RGI2000-v7.0-G-08-03031` | `TrÃ¦sfonn` | Træsfonn |
| `RGI2000-v7.0-G-08-03044` | `GrÃ¥fjellsbrea` | Gråfjellsbrea |
| `RGI2000-v7.0-G-08-03048` | `BlÃ¥fonna` | Blåfonna |
| `RGI2000-v7.0-G-08-03072` | `SÃ¸re Skavlen` | Søre Skavlen |
| `RGI2000-v7.0-G-08-03091` | `BlÃ¥isen` | Blåisen |
| `RGI2000-v7.0-G-08-03132` | `MjÃ¸lkedalsbreen` | Mjølkedalsbreen |
| `RGI2000-v7.0-G-08-03139` | `HÃ¸gvaglbreen` | Høgvaglbreen |
| `RGI2000-v7.0-G-08-03140` | `HÃ¸gvaglbreen` | Høgvaglbreen |
| `RGI2000-v7.0-G-08-03145` | `BjÃ¸rnbrean` | Bjørnbrean |
| `RGI2000-v7.0-G-08-03156` | `BÃ¸verbrean` | Bøverbrean |
| `RGI2000-v7.0-G-08-03162` | `SÃ¸re IllÃ¥breen` | Søre Illåbreen |
| `RGI2000-v7.0-G-08-03163` | `TverrÃ¥brean` | Tverråbrean |
| `RGI2000-v7.0-G-08-03176` | `Heimre IllÃ¥brean` | Heimre Illåbrean |
| `RGI2000-v7.0-G-08-03177` | `DumhÃ¸brean` | Dumhøbrean |
| `RGI2000-v7.0-G-08-03180` | `NÃ¸rdre IllÃ¥brean` | Nørdre Illåbrean |
| `RGI2000-v7.0-G-08-03181` | `HÃ¸gskridubrean` | Høgskridubrean |
| `RGI2000-v7.0-G-08-03188` | `HÃ¸ybrean` | Høybrean |
| `RGI2000-v7.0-G-08-03204` | `MÃ¸yldulbreen` | Møyldulbreen |
| `RGI2000-v7.0-G-08-03218` | `HolÃ¥breen` | Holåbreen |
| `RGI2000-v7.0-G-08-03220` | `Midtre GjelÃ¥breen` | Midtre Gjelåbreen |
| `RGI2000-v7.0-G-08-03221` | `Ytre GjelÃ¥breen` | Ytre Gjelåbreen |
| `RGI2000-v7.0-G-08-03243` | `HolÃ¥breen` | Holåbreen |
| `RGI2000-v7.0-G-08-03250` | `MÃ¥rÃ¥dalsbreen` | Mårådalsbreen |
| `RGI2000-v7.0-G-08-03259` | `SandÃ¥breen` | Sandåbreen |
| `RGI2000-v7.0-G-08-03267` | `Heimstre GjelÃ¥breen` | Heimstre Gjelåbreen |
| `RGI2000-v7.0-G-08-03271` | `GrjotÃ¥breen` | Grjotåbreen |
| `RGI2000-v7.0-G-08-03322` | `StyggehÃ¸brean` | Styggehøbrean |
| `RGI2000-v7.0-G-08-03325` | `BlÃ¥brean` | Blåbrean |
| `RGI2000-v7.0-G-08-03351` | `GrÃ¥subrean` | Gråsubrean |
| `RGI2000-v7.0-G-08-03363` | `BesshÃ¸brean` | Besshøbrean |
| `RGI2000-v7.0-G-08-03382` | `KalvehÃ¸gdbreene` | Kalvehøgdbreene |
| `RGI2000-v7.0-G-10-00765` | `14Ð°` | 14а |
| `RGI2000-v7.0-G-10-00769` | `24Ð°` | 24а |
| `RGI2000-v7.0-G-10-00777` | `16Ð°` | 16а |
| `RGI2000-v7.0-G-10-00782` | `10Ð°` | 10а |
| `RGI2000-v7.0-G-10-00787` | `1Ð°` | 1а |
| `RGI2000-v7.0-G-10-00789` | `68Ð°` | 68а |
| `RGI2000-v7.0-G-10-00806` | `41Ð°` | 41а |
| `RGI2000-v7.0-G-10-00807` | `43Ð°` | 43а |
| `RGI2000-v7.0-G-10-00822` | `54Ð°` | 54а |
| `RGI2000-v7.0-G-10-00834` | `63Ð°` | 63а |
| `RGI2000-v7.0-G-10-00835` | `58Ð°` | 58а |
| `RGI2000-v7.0-G-10-00848` | `85Ð°` | 85а |
| `RGI2000-v7.0-G-10-00859` | `105Ð°` | 105а |
| `RGI2000-v7.0-G-10-00865` | `109Ð°` | 109а |
| `RGI2000-v7.0-G-10-00880` | `101Ð°` | 101а |
| `RGI2000-v7.0-G-10-00883` | `112Ð°` | 112а |
| `RGI2000-v7.0-G-10-00890` | `116Ð°` | 116а |
| `RGI2000-v7.0-G-10-00892` | `117Ð°` | 117а |
| `RGI2000-v7.0-G-10-00897` | `121Ð°` | 121а |
| `RGI2000-v7.0-G-10-00898` | `121Ð°` | 121а |
| `RGI2000-v7.0-G-10-00915` | `143Ð°` | 143а |
| `RGI2000-v7.0-G-10-00942` | `160Ð°` | 160а |
| `RGI2000-v7.0-G-11-00795` | `Mont V\x82lan-W` | Mont Vélan-W |
| `RGI2000-v7.0-G-11-00822` | `Combin de Corbassi\x8are-E` | Combin de Corbassière-E |
| `RGI2000-v7.0-G-11-00907` | `MONT MIN\x90 GLACIER DU` | MONT MINÉ GLACIER DU |
| `RGI2000-v7.0-G-11-00908` | `Mont Min\x82-S-II` | Mont Miné-S-II |
| `RGI2000-v7.0-G-11-00909` | `Mont Min\x82-S-I` | Mont Miné-S-I |
| `RGI2000-v7.0-G-11-00941` | `SCH\x99LLI GLETSCHER` | SCHÖLLI GLETSCHER |
| `RGI2000-v7.0-G-11-00944` | `\x9assers Barrhorn` | Üssers Barrhorn |
| `RGI2000-v7.0-G-11-00947` | `BR\x8eNDJI GLETSCHER` | BRÄNDJI GLETSCHER |
| `RGI2000-v7.0-G-11-00960` | `T\x88te de Milon-N` | Tête de Milon-N |
| `RGI2000-v7.0-G-11-00977` | `HOHW\x8eNGGLETSCHER` | HOHWÄNGGLETSCHER |
| `RGI2000-v7.0-G-11-01061` | `Pigne de la L\x82-N` | Pigne de la Lé-N |
| `RGI2000-v7.0-G-11-01072` | `L\x84ngfluejoch-E` | Längfluejoch-E |
| `RGI2000-v7.0-G-11-01087` | `T\x8eLLIBODENGLETSCHER` | TÄLLIBODENGLETSCHER |
| `RGI2000-v7.0-G-11-01102` | `T\x84llihorn-SW` | Tällihorn-SW |
| `RGI2000-v7.0-G-11-01104` | `T\x8eLLIGLETSCHER-W` | TÄLLIGLETSCHER-W |
| `RGI2000-v7.0-G-11-01111` | `M\x8eLLIGA GLETSCHER` | MÄLLIGA GLETSCHER |
| `RGI2000-v7.0-G-11-01127` | `GR\x9aEBUGLETSCHER-S` | GRÜEBUGLETSCHER-S |
| `RGI2000-v7.0-G-11-01129` | `GR\x9aEBUGLETSCHER-N-I` | GRÜEBUGLETSCHER-N-I |
| `RGI2000-v7.0-G-11-01136` | `B\x94shorn-NE` | Böshorn-NE |
| `RGI2000-v7.0-G-11-01140` | `T\x84lligletscher-E` | Tälligletscher-E |
| `RGI2000-v7.0-G-11-01175` | `D\x9aRRENGLETSCHER` | DÜRRENGLETSCHER |
| `RGI2000-v7.0-G-11-01176` | `Hohgw\x84chte` | Hohgwächte |
| `RGI2000-v7.0-G-11-01183` | `\x9assere Turu-SW` | Üssere Turu-SW |
| `RGI2000-v7.0-G-11-01254` | `L\x99TSCHENGLETSCHER` | LÖTSCHENGLETSCHER |
| `RGI2000-v7.0-G-11-01260` | `L\x99TSCHENGLETSCHER` | LÖTSCHENGLETSCHER |
| `RGI2000-v7.0-G-11-01271` | `T\x8eLLIGLETSCHER` | TÄLLIGLETSCHER |
| `RGI2000-v7.0-G-11-01272` | `T\x8eLLIGLETSCHER` | TÄLLIGLETSCHER |
| `RGI2000-v7.0-G-11-01287` | `L\x8eMMERENGLETSCHER` | LÄMMERENGLETSCHER |
| `RGI2000-v7.0-G-11-01314` | `T\x88te Ronde-NW` | Tête Ronde-NW |
| `RGI2000-v7.0-G-11-01367` | `Tour Salli\x8are Glacier de la -II` | Tour Sallière Glacier de la -II |
| `RGI2000-v7.0-G-11-01451` | `Tennbachl\x81cke-NW` | Tennbachlücke-NW |
| `RGI2000-v7.0-G-11-01453` | `Elwert\x84tsch-W` | Elwertätsch-W |
| `RGI2000-v7.0-G-11-01465` | `BL\x9aMLISALPGLETSCHER` | BLÜMLISALPGLETSCHER |
| `RGI2000-v7.0-G-11-01468` | `Fr\x81ndenhorn-NW` | Fründenhorn-NW |
| `RGI2000-v7.0-G-11-01469` | `Fr\x81ndenhorn-SE` | Fründenhorn-SE |
| `RGI2000-v7.0-G-11-01471` | `Bl\x81emlisalphorn-SE` | Blüemlisalphorn-SE |
| `RGI2000-v7.0-G-11-01472` | `FR\x9aNDEN GLETSCHER` | FRÜNDEN GLETSCHER |
| `RGI2000-v7.0-G-11-01479` | `Fr\x81ndenjoch-S` | Fründenjoch-S |
| `RGI2000-v7.0-G-11-01490` | `B\x81tlasse-SE` | Bütlasse-SE |
| `RGI2000-v7.0-G-11-01491` | `B\x81tlasse-NW` | Bütlasse-NW |
| `RGI2000-v7.0-G-11-01531` | `SCH\x99NB\x9aHLGLETSCHER-NW` | SCHÖNBÜHLGLETSCHER-NW |
| `RGI2000-v7.0-G-11-01536` | `Gr\x81negg-NE` | Grünegg-NE |
| `RGI2000-v7.0-G-11-01554` | `N\x99RDLICHER BREITLOUWENENGLETSCHER` | NÖRDLICHER BREITLOUWENENGLETSCHER |
| `RGI2000-v7.0-G-11-01555` | `S\x9aDLICHER BREITLOUWENENGLETSCHER` | SÜDLICHER BREITLOUWENENGLETSCHER |
| `RGI2000-v7.0-G-11-01556` | `B\x84renflue` | Bärenflue |
| `RGI2000-v7.0-G-11-01571` | `Eiger S\x81dwestgrat` | Eiger Südwestgrat |
| `RGI2000-v7.0-G-11-01605` | `Lauteraar-Roth\x94rner-W` | Lauteraar-Rothörner-W |
| `RGI2000-v7.0-G-11-01610` | `Lauteraar-Roth\x94rner-NE` | Lauteraar-Rothörner-NE |
| `RGI2000-v7.0-G-11-01621` | `W\x8eCHSELGLETSCHER` | WÄCHSELGLETSCHER |
| `RGI2000-v7.0-G-11-01633` | `R\x84nfenjoch-E` | Ränfenjoch-E |
| `RGI2000-v7.0-G-11-01646` | `R\x84nfenhorn-SE` | Ränfenhorn-SE |
| `RGI2000-v7.0-G-11-01648` | `\x99stl. Ankeb\x84llil\x81cke-S` | Östl. Ankebällilücke-S |
| `RGI2000-v7.0-G-11-01665` | `B\x8eCHLIGLETSCHER` | BÄCHLIGLETSCHER |
| `RGI2000-v7.0-G-11-01677` | `\x8eRLENGLETSCHER-S` | ÄRLENGLETSCHER-S |
| `RGI2000-v7.0-G-11-01678` | `\x8eRLENGLETSCHER-N` | ÄRLENGLETSCHER-N |
| `RGI2000-v7.0-G-11-01691` | `\x8eLPLIGLETSCHER` | ÄLPLIGLETSCHER |
| `RGI2000-v7.0-G-11-01693` | `G\x84rstenlicke-N` | Gärstenlicke-N |
| `RGI2000-v7.0-G-11-01695` | `G\x8eRSTENGLETSCHER` | GÄRSTENGLETSCHER |
| `RGI2000-v7.0-G-11-01696` | `G\x8eRSTENGLETSCHER` | GÄRSTENGLETSCHER |
| `RGI2000-v7.0-G-11-01697` | `G\x84rstenlicke` | Gärstenlicke |
| `RGI2000-v7.0-G-11-01722` | `M\x84ssplanggstock` | Mässplanggstock |
| `RGI2000-v7.0-G-11-01738` | `Gw\x84chtenhorn` | Gwächtenhorn |
| `RGI2000-v7.0-G-11-01748` | `R\x9aTIFIRN` | RÜTIFIRN |
| `RGI2000-v7.0-G-11-01768` | `Triftt\x84lli` | Trifttälli |
| `RGI2000-v7.0-G-11-01793` | `B\x8eCHENFIRN-I` | BÄCHENFIRN-I |
| `RGI2000-v7.0-G-11-01811` | `Ober\x84lpler` | Oberälpler |
| `RGI2000-v7.0-G-11-01813` | `B\x8eCHENFIRN` | BÄCHENFIRN |
| `RGI2000-v7.0-G-11-01857` | `H\x8eLSIFIRN` | HÄLSIFIRN |
| `RGI2000-v7.0-G-11-01866` | `ST\x8eFELIFIRN` | STÄFELIFIRN |
| `RGI2000-v7.0-G-11-01867` | `ST\x8eFELIFIRN` | STÄFELIFIRN |
| `RGI2000-v7.0-G-11-01869` | `WINDG\x8eLLENFIRN` | WINDGÄLLENFIRN |
| `RGI2000-v7.0-G-11-01870` | `H\x9aFIFIRN` | HÜFIFIRN |
| `RGI2000-v7.0-G-11-01877` | `HINTER R\x99TIFIRN-S` | HINTER RÖTIFIRN-S |
| `RGI2000-v7.0-G-11-01878` | `HINTER R\x99TIFIRN` | HINTER RÖTIFIRN |
| `RGI2000-v7.0-G-11-01880` | `VORDERER R\x99TIFIRN` | VORDERER RÖTIFIRN |
| `RGI2000-v7.0-G-11-01983` | `FUTSCH\x99L VADRET` | FUTSCHÖL VADRET |
| `RGI2000-v7.0-G-11-02053` | `J\x99RIGLETSCHER` | JÖRIGLETSCHER |
| `RGI2000-v7.0-G-11-02055` | `RAD\x99NT VADRET DA` | RADÖNT VADRET DA |
| `RGI2000-v7.0-G-11-02069` | `GLETSCHT\x8eLI` | GLETSCHTÄLI |
| `RGI2000-v7.0-G-11-02071` | `CH\x9aEALP  GLETSCHER` | CHÜEALP  GLETSCHER |
| `RGI2000-v7.0-G-11-02099` | `GIAVI\x99L VADRET DAL` | GIAVIÖL VADRET DAL |
| `RGI2000-v7.0-G-11-02101` | `G\x9aGLIA VADRET-S` | GÜGLIA VADRET-S |
| `RGI2000-v7.0-G-11-02110` | `CHAP\x9aTSCHIN VADRET DAL` | CHAPÜTSCHIN VADRET DAL |
| `RGI2000-v7.0-G-11-02111` | `CHAP\x9aTSCHIN VADRETTIN DAL` | CHAPÜTSCHIN VADRETTIN DAL |
| `RGI2000-v7.0-G-11-02123` | `G\x9aZ VADRET DAL` | GÜZ VADRET DAL |
| `RGI2000-v7.0-G-11-02223` | `PAL\x9a VADRET DA` | PALÜ VADRET DA |
| `RGI2000-v7.0-G-11-02240` | `Piz Pr\x81na-I` | Piz Prüna-I |
| `RGI2000-v7.0-G-11-02244` | `PAL\x9aD MARSCHA VADRET` | PALÜD MARSCHA VADRET |
| `RGI2000-v7.0-G-11-02245` | `PAL\x9aD MARSCHA VADRET` | PALÜD MARSCHA VADRET |
| `RGI2000-v7.0-G-11-02253` | `T\x84lihorn-N` | Tälihorn-N |
| `RGI2000-v7.0-G-11-02308` | `Furcela dal Sc\x84lin.` | Furcela dal Scälin. |
| `RGI2000-v7.0-G-11-02345` | `H\x99HBERG GLETSCHER` | HÖHBERG GLETSCHER |
| `RGI2000-v7.0-G-11-02352` | `G\x81ferhorn-W` | Güferhorn-W |
| `RGI2000-v7.0-G-11-02354` | `G\x9aFERGLETSCHER` | GÜFERGLETSCHER |
| `RGI2000-v7.0-G-11-02356` | `L\x8eNTAGLETSCHER` | LÄNTAGLETSCHER |
| `RGI2000-v7.0-G-11-02410` | `Rott\x84lli-W` | Rottälli-W |
| `RGI2000-v7.0-G-11-02416` | `Muttenst\x94ck` | Muttenstöck |
| `RGI2000-v7.0-G-11-02417` | `Deieren\x84lpetli-W` | Deierenälpetli-W |
| `RGI2000-v7.0-G-11-02423` | `CH\x9aEBODENGLETSCHER-II` | CHÜEBODENGLETSCHER-II |
| `RGI2000-v7.0-G-11-02425` | `CH\x9aEBODENGLETSCHER-III` | CHÜEBODENGLETSCHER-III |
| `RGI2000-v7.0-G-11-02434` | `Ritzh\x94rner-N` | Ritzhörner-N |
| `RGI2000-v7.0-G-11-02450` | `F\x8eLDBACHGLETSCHER` | FÄLDBACHGLETSCHER |
| `RGI2000-v7.0-G-11-02451` | `F\x8eLDBACHGLETSCHER` | FÄLDBACHGLETSCHER |
| `RGI2000-v7.0-G-11-02458` | `T\x8eLLIGLETSCHER-N` | TÄLLIGLETSCHER-N |
| `RGI2000-v7.0-G-11-02463` | `T\x8eLLIGLETSCHER-S` | TÄLLIGLETSCHER-S |
| `RGI2000-v7.0-G-11-02473` | `CAVAGN\x99\x99 GH. DEL` | CAVAGNÖÖ GH. DEL |
| `RGI2000-v7.0-G-11-02525` | `Zenb\x84chenhorn-E` | Zenbächenhorn-E |
| `RGI2000-v7.0-G-11-02532` | `S\x81dl. Wysshorn-SW` | Südl. Wysshorn-SW |
| `RGI2000-v7.0-G-11-02533` | `S\x81dl. Wysshorn-S` | Südl. Wysshorn-S |
| `RGI2000-v7.0-G-11-02581` | `\x9aSSRE BALTSCHIEDERGLETSCHER` | ÜSSRE BALTSCHIEDERGLETSCHER |
| `RGI2000-v7.0-G-11-02591` | `UNNERB\x8eCHGLETSCHER-Mitte` | UNNERBÄCHGLETSCHER-Mitte |
| `RGI2000-v7.0-G-11-02592` | `UNNERB\x8eCHGLETSCHER-E` | UNNERBÄCHGLETSCHER-E |
| `RGI2000-v7.0-G-11-02593` | `UNNERB\x8eCHGLETSCHER-E` | UNNERBÄCHGLETSCHER-E |
| `RGI2000-v7.0-G-11-02594` | `Kort\x84lli` | Kortälli |
| `RGI2000-v7.0-G-11-02595` | `UNNERB\x8eCHGLETSCHER-W` | UNNERBÄCHGLETSCHER-W |
| `RGI2000-v7.0-G-11-02597` | `SCH\x99NB\x9aHLGLETSCHER-SE` | SCHÖNBÜHLGLETSCHER-SE |
| `RGI2000-v7.0-G-11-02616` | `B\x8eCHIGLETSCHER` | BÄCHIGLETSCHER |
| `RGI2000-v7.0-G-11-02620` | `Heizw\x84chte-NE` | Heizwächte-NE |
| `RGI2000-v7.0-G-11-02621` | `Roosseh\x94rner-NE` | Roossehörner-NE |
| `RGI2000-v7.0-G-11-02639` | `L\x94ffelhorn-SE` | Löffelhorn-SE |
| `RGI2000-v7.0-G-11-02640` | `L\x94ffelhorn-N` | Löffelhorn-N |
| `RGI2000-v7.0-G-11-02655` | `N\x84ssihorn-SW` | Nässihorn-SW |
| `RGI2000-v7.0-G-11-02658` | `\x9aSSER TALGLETSCHER` | ÜSSER TALGLETSCHER |
| `RGI2000-v7.0-G-11-02675` | `ST\x99SSENFIRN-II` | STÖSSENFIRN-II |
| `RGI2000-v7.0-G-11-02676` | `ST\x99SSENFIRN-III` | STÖSSENFIRN-III |
| `RGI2000-v7.0-G-11-02685` | `CH\x9aEFADFIRN-W` | CHÜEFADFIRN-W |
| `RGI2000-v7.0-G-11-02686` | `CH\x9aEFADFIRN-W` | CHÜEFADFIRN-W |
| `RGI2000-v7.0-G-11-02687` | `B\x84rengrueben` | Bärengrueben |
| `RGI2000-v7.0-G-11-02688` | `B\x84renz\x84hn` | Bärenzähn |
| `RGI2000-v7.0-G-11-02691` | `Ch\x81efadstock` | Chüefadstock |
| `RGI2000-v7.0-G-11-02692` | `Ch\x81efadfirn-E` | Chüefadfirn-E |
| `RGI2000-v7.0-G-11-02696` | `Zw\x84chten` | Zwächten |
| `RGI2000-v7.0-G-11-02697` | `B\x8eCHENFIRN` | BÄCHENFIRN |
| `RGI2000-v7.0-G-11-02698` | `SEWENZW\x8eCHTEN` | SEWENZWÄCHTEN |
| `RGI2000-v7.0-G-11-02699` | `B\x84chen-S` | Bächen-S |
| `RGI2000-v7.0-G-11-02704` | `Kr\x94nten` | Krönten |
| `RGI2000-v7.0-G-11-02706` | `Chli Kr\x94nten` | Chli Krönten |
| `RGI2000-v7.0-G-11-02707` | `Chli Kr\x94nten-E` | Chli Krönten-E |
| `RGI2000-v7.0-G-11-02719` | `BL\x9aEMLISALPFIRN` | BLÜEMLISALPFIRN |
| `RGI2000-v7.0-G-11-02723` | `SCH\x99NTALER FIRN` | SCHÖNTALER FIRN |
| `RGI2000-v7.0-G-11-02729` | `ST\x99SSENFIRN-II` | STÖSSENFIRN-II |
| `RGI2000-v7.0-G-11-02781` | `B\x94s Fulen-S` | Bös Fulen-S |
| `RGI2000-v7.0-G-11-02785` | `B\x8eCHIFIRN` | BÄCHIFIRN |
| `RGI2000-v7.0-G-11-02788` | `Radt\x84lli` | Radtälli |
| `RGI2000-v7.0-G-11-02789` | `GL\x8eRNISCHFIRN` | GLÄRNISCHFIRN |
| `RGI2000-v7.0-G-12-00064` | `958Ð°` | 958а |
| `RGI2000-v7.0-G-12-00149` | `885Ð°` | 885а |
| `RGI2000-v7.0-G-12-00150` | `885Ð°` | 885а |
| `RGI2000-v7.0-G-12-00197` | `868Ð°` | 868а |
| `RGI2000-v7.0-G-12-00272` | `746Ð°` | 746а |
| `RGI2000-v7.0-G-12-00289` | `740Ð°` | 740а |
| `RGI2000-v7.0-G-12-00290` | `740Ð°` | 740а |
| `RGI2000-v7.0-G-12-00470` | `630Ð°` | 630а |
| `RGI2000-v7.0-G-12-00493` | `148Ð°` | 148а |
| `RGI2000-v7.0-G-12-00505` | `602Ð°` | 602а |
| `RGI2000-v7.0-G-12-00517` | `598Ð°` | 598а |
| `RGI2000-v7.0-G-12-00521` | `527Ð°` | 527а |
| `RGI2000-v7.0-G-12-00522` | `528Ð°` | 528а |
| `RGI2000-v7.0-G-12-00525` | `526Ð°` | 526а |
| `RGI2000-v7.0-G-12-00528` | `524Ð°` | 524а |
| `RGI2000-v7.0-G-12-00531` | `522Ð°` | 522а |
| `RGI2000-v7.0-G-12-00558` | `193Ð°` | 193а |
| `RGI2000-v7.0-G-12-00600` | `216Ð°` | 216а |
| `RGI2000-v7.0-G-12-00639` | `508Ð°` | 508а |
| `RGI2000-v7.0-G-12-00650` | `494Ð°` | 494а |
| `RGI2000-v7.0-G-12-00661` | `499Ð°` | 499а |
| `RGI2000-v7.0-G-12-00700` | `241Ð°` | 241а |
| `RGI2000-v7.0-G-12-00744` | `474Ð°` | 474а |
| `RGI2000-v7.0-G-12-00757` | `488Ð°` | 488а |
| `RGI2000-v7.0-G-12-00760` | `490Ð°` | 490а |
| `RGI2000-v7.0-G-12-00785` | `464Ð°` | 464а |
| `RGI2000-v7.0-G-12-00796` | `470Ð°` | 470а |
| `RGI2000-v7.0-G-12-00814` | `442Ð°` | 442а |
| `RGI2000-v7.0-G-12-00967` | `535Ð°` | 535а |
| `RGI2000-v7.0-G-12-00974` | `556Ð°` | 556а |
| `RGI2000-v7.0-G-12-00985` | `549Ð°` | 549а |
| `RGI2000-v7.0-G-12-01014` | `532Ð°` | 532а |
| `RGI2000-v7.0-G-12-01062` | `145Ð°` | 145а |
| `RGI2000-v7.0-G-12-01076` | `143Ð°` | 143а |
| `RGI2000-v7.0-G-12-01083` | `147Ð°` | 147а |
| `RGI2000-v7.0-G-12-01135` | `767Ð°` | 767а |
| `RGI2000-v7.0-G-12-01137` | `766Ð°` | 766а |
| `RGI2000-v7.0-G-12-01266` | `302Ð°` | 302а |
| `RGI2000-v7.0-G-12-01269` | `302Ð°` | 302а |
| `RGI2000-v7.0-G-12-01270` | `302Ð°` | 302а |
| `RGI2000-v7.0-G-12-01357` | `324Ð°` | 324а |
| `RGI2000-v7.0-G-12-01380` | `412Ð°` | 412а |
| `RGI2000-v7.0-G-12-01407` | `359Ðµ` | 359е |
| `RGI2000-v7.0-G-12-01427` | `357Ð°` | 357а |
| `RGI2000-v7.0-G-12-01482` | `326Ð°` | 326а |
| `RGI2000-v7.0-G-12-01484` | `325Ð°` | 325а |
| `RGI2000-v7.0-G-12-01485` | `324Ð°` | 324а |
| `RGI2000-v7.0-G-12-01520` | `343Ð°` | 343а |
| `RGI2000-v7.0-G-12-01522` | `344Ð°` | 344а |
| `RGI2000-v7.0-G-12-01545` | `298Ð°` | 298а |
| `RGI2000-v7.0-G-12-01560` | `302Ð°` | 302а |
| `RGI2000-v7.0-G-12-01581` | `263Ð°` | 263а |
| `RGI2000-v7.0-G-12-01591` | `221Ð°` | 221а |
| `RGI2000-v7.0-G-12-01592` | `229Ð°` | 229а |
| `RGI2000-v7.0-G-12-01646` | `260Ð²` | 260в |
| `RGI2000-v7.0-G-12-01647` | `259Ð°` | 259а |
| `RGI2000-v7.0-G-12-01695` | `183Ð°` | 183а |
| `RGI2000-v7.0-G-12-01705` | `179Ð°` | 179а |
| `RGI2000-v7.0-G-12-01709` | `187Ð°` | 187а |
| `RGI2000-v7.0-G-12-01717` | `177Ð°` | 177а |
| `RGI2000-v7.0-G-12-01908` | `402Ð°` | 402а |
| `RGI2000-v7.0-G-12-01970` | `9Ð°` | 9а |
| `RGI2000-v7.0-G-12-02016` | `277Ð°` | 277а |
| `RGI2000-v7.0-G-12-02157` | `940Ð°` | 940а |
| `RGI2000-v7.0-G-12-02158` | `943Ð°` | 943а |

</details>

### RGI 6.0 links

The links between RGI 7.0 and RGI 6.0 glaciers in the glacier product zip
are wrong. "A bug in the RGI7 processing pipeline led to all RGI6 to RGI7
overlaps smaller than 200 **km2** to be filtered out"
([rgi_issue_tracker#41](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/41)).
The build reads the corrected file `RGI2000-v7.0-G-global-rgi6_links.csv`
instead. It holds 298,256 links. 221,676 glaciers have at least one link,
and 52,855 have none.

## `display_name`

`display_name` is the glacier name drawn on the map. It is derived from
`glac_name` after the encoding repair. `glac_name` keeps RGI's value, and
`rgi_id` is the key, never the name.

An override in `metadata/name_overrides.yaml` replaces the rules for one
`glac_name`. The overrides are listed below. Otherwise the rules run in this
order (`src/rgi_catalog/names.py`):

1. Underscores become spaces, and runs of whitespace collapse to one space.
   A trailing comma is dropped. A dash that stands for an empty second name
   is dropped too: `Austfonna, -` becomes `Austfonna`.
2. Inventory codes are removed as whole tokens at either end of the name.
   These are GLIMS and WGI codes: two capital letters, a digit, then five or
   more letters or digits, such as `CN5Y673P0037`. A range or query suffix
   such as `-10`, `+05` or `?` is part of the code.
3. The name is null when nothing is left. It is also null for `S/N`, `NN`,
   `Unnamed` with an optional number, `None`, `<Null>`, `No Name`,
   `No Name Glacier` and `Namenlos` with an optional Roman numeral. Names that
   are only digits, codes of one to three capitals, and names that are only a
   bracket, such as `(Severny Island)`, are null too.
4. A Cyrillic `а`, `е` or `в` after digits becomes the Latin `a`, `e` or `v`:
   `101а` becomes `101a`. 362 other names of this form in regions 10 and 12
   use the Latin letter.
5. A backtick or an acute accent used as an apostrophe becomes `'`:
   `Shkhel`dy` becomes `Shkhel'dy`.
6. A bracket has a space before it and no space inside it. A slash with a
   space on one side only gets a space on both sides.
7. A hyphen before a compass point, a Roman numeral or `Mitte` becomes a
   space, as in the Swiss Glacier Inventory: `Tälligletscher-E` becomes
   `Tälligletscher E`. After an apostrophe the hyphen is dropped:
   `GLACIER DE L'-N` becomes `Glacier de l'N`.
8. A name with no lowercase letter is re-cased. Each word starts with a
   capital and continues in lowercase. Roman numerals and compass points
   stay in capitals, and so does a Swiss canton code that ends the name
   (`FIESCHERGLETSCHER VS` becomes `Fieschergletscher VS`). A word that holds
   a digit keeps its case (`HPS34`). Particles such as `de`, `du`, `del`,
   `dal`, `dil`, `la` and `d'` are lowercase unless they start the name, and
   the letter after `O'` is a capital. Words are never reordered. In a
   mixed-case name only the words of four or more capitals are re-cased
   (`TUNGELGLETSCHER09n` becomes `Tungelgletscher09n`). A word that mixes
   cases is kept as written (`MIIGAiK`).
9. In region 11, a name that starts with `d'`, `de`, `du` or `des` gets
   `Glacier` in front. The French Glacier Inventory leaves the word out:
   `FR4N01154Q12 d'Ambin` becomes `Glacier d'Ambin`.
10. A name that starts with a lowercase letter gets a capital.

A `?` at the end of a word stays. In the French Glacier Inventory it marks an
uncertain name, such as `du Col de Sirac?`.

How often each rule applies, over the 274,531 glaciers. One name can match
more than one rule.

| Rule | Glaciers |
| --- | ---: |
| `empty`: no `glac_name` | 216,535 |
| `override` | 5 |
| `underscores` | 52 |
| `trailing-comma` | 290 |
| `empty-second-name` | 27 |
| `inventory-code-stripped`, a name is left | 890 |
| `code-only` | 23,307 |
| `no-name-marker` | 18,422 |
| `numeric-only` | 1,621 |
| `short-code` | 4,645 |
| `bracket-only` | 542 |
| `cyrillic-suffix` | 87 |
| `apostrophe` | 6 |
| `spacing` | 5 |
| `suffix-hyphen` | 358 |
| `recased` | 1,118 |
| `french-glacier` | 415 |
| `initial-capital` | 9 |
| `unchanged` | 6,825 |

57,996 glaciers have a non-empty `glac_name`, and 9,457 have a
`display_name`.

### Overrides

| RGI's `glac_name` | `display_name` | Reason |
| --- | --- | --- |
| `Previously a part of Murraybreen` | null | The glac_name is a note. |
| `Vegfonna, Previously attached to Rosenthalbreen` | Vegfonna | The text after the comma is a note. |
| `Group of small glaciers` | null | The glac_name is a description. |
| `FR4N01235A08 dArgentiere` | Glacier d'Argentiere | The apostrophe of the particle d' is missing. |
| `SHCHuchij` | Shchuchij | The first letters are capitals by mistake. |

### Names the rules leave as published

These upstream errors stay in `display_name` as RGI publishes them:

- A non-ASCII letter that the submission lost. Some names in region 11 drop
  it (`Hallsttter Gletscher`). Some names in regions 11, 17 and 19 have `?`
  in its place (`Gl. R?o Blanco`).
- Spelling errors, such as `Chalresbreenn` in region 07.

## Known issues

The build does not fix these upstream issues. Each is open in the RGI issue
tracker.

- [rgi_issue_tracker#21](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/21),
  "Glacier complex product may have artifacts at glacier divides". The issue shows
  glacier outlines at a divide that are "close", but not quite touching.
- [rgi_issue_tracker#27](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/27),
  "ANLYS_IDs are not truly unique". In the glaciers file, 148 `anlys_id`
  values are shared by 353 glaciers. Do not join on `anlys_id`.
- [rgi_issue_tracker#58](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/58),
  "Missing glaciers in Greenland". The issue gives two glaciers, at 81.929°N,
  27.270°W and 77.626°N, 67.376°W.
- [rgi_issue_tracker#63](https://github.com/GLIMS-RGI/rgi_issue_tracker/issues/63),
  "Missing glaciers in the Aleutian Islands". The issue names glaciers on
  Tanaga Island and Attu Island.
