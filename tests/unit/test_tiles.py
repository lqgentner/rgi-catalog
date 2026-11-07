"""Tests for the web-map archive."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
from pmtiles.reader import MmapSource, Reader, all_tiles
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon

from rgi_catalog import assemble, glyphs, styles, tiles
from rgi_catalog.geoparquet import write_geoparquet
from rgi_catalog.tiles import (
    LayerSpec,
    build_archive,
    decode,
    glacier_layers,
    label_minzoom,
    tile_properties,
    write_labels,
)

if TYPE_CHECKING:
    from tests.unit.conftest import FakeRGI

LINK = pa.struct([("rgi6_id", pa.string()), ("overlap_area_km2", pa.float64())])
KV = {
    "rgi:version": "7.0",
    "rgi:mirror_revision": "7.0-r1",
    "rgi:sources": "{}",
    "rgi:citation": "RGI 7.0 Consortium, 2023.",
    "rgi:catalog": "https://data.source.coop/lqgentner/rgi/catalog.json",
}
META = {"name": "x", "attribution": "x", "description": "x"}

# (rgi_id, cenlon, cenlat, area_km2, display_name). Region 10 sits on the
# antimeridian, so one glacier lies at longitude 179.95.
GLACIERS = [
    ("RGI2000-v7.0-G-11-00001", 10.755, 46.805, 6.0, "Hintereisferner"),
    ("RGI2000-v7.0-G-11-00002", 10.805, 46.855, 0.5, None),
    ("RGI2000-v7.0-G-11-00003", 10.905, 46.905, 0.2, "Tiny Glacier"),
    ("RGI2000-v7.0-G-10-00001", 179.95, 65.005, 100.0, "Antimeridian Glacier"),
    ("RGI2000-v7.0-G-01-00001", -147.0, 61.0, 1000.0, "Big Glacier"),
]
# Half the side of each fixture square, in degrees. The big glacier spans a
# degree, so it is a shape from a low zoom on.
HALF_SIDE = {"RGI2000-v7.0-G-01-00001": 0.5}
BIG = "RGI2000-v7.0-G-01-00001"


def _glaciers_frame() -> gpd.GeoDataFrame:
    n = len(GLACIERS)
    permille = pa.array([[500, 500]] * n, type=pa.list_(pa.int16()))
    link = {"rgi6_id": "RGI60-11.00001", "overlap_area_km2": 0.5}
    links = pa.array([[link]] * n, type=pa.list_(LINK))
    return gpd.GeoDataFrame(
        {
            "rgi_id": [g[0] for g in GLACIERS],
            "o1region": [g[0][15:17] for g in GLACIERS],
            "cenlon": [g[1] for g in GLACIERS],
            "cenlat": [g[2] for g in GLACIERS],
            "area_km2": [g[3] for g in GLACIERS],
            "term_type": pd.Series([0, 0, 1, 2, 9], dtype="uint8"),
            "display_name": [g[4] for g in GLACIERS],
            "hypso_permille": pd.Series(permille, dtype=pd.ArrowDtype(permille.type)),
            "rgi6_links": pd.Series(links, dtype=pd.ArrowDtype(links.type)),
        },
        geometry=[
            Polygon(
                [
                    (lon - h, lat - h),
                    (lon + h, lat - h),
                    (lon + h, lat + h),
                    (lon - h, lat + h),
                ],
            )
            for rgi_id, lon, lat, _, _ in GLACIERS
            for h in [HALF_SIDE.get(rgi_id, 0.005)]
        ],
        crs="EPSG:4326",
    )


@pytest.fixture(scope="module")
def glaciers_parquet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tiles") / "rgi7.0-glaciers.parquet"
    write_geoparquet(_glaciers_frame(), out, kv=KV)
    return out


# (rgi_g_id, is_main, line). Big Glacier has two main lines and the longer
# one carries its name. The line of Hintereisferner is too short for its name
# at any zoom.
LABEL_CENTERLINES = [
    (BIG, True, [(-147.4, 61.0), (-146.6, 61.0)]),
    (BIG, True, [(-147.1, 61.1), (-146.9, 61.1)]),
    (BIG, False, [(-147.4, 61.2), (-146.4, 61.2)]),
    ("RGI2000-v7.0-G-11-00001", True, [(10.753, 46.805), (10.757, 46.805)]),
]


@pytest.fixture(scope="module")
def label_centerlines_parquet(glaciers_parquet: Path) -> Path:
    out = glaciers_parquet.parent / "centerlines.parquet"
    gpd.GeoDataFrame(
        {
            "rgi_g_id": [c[0] for c in LABEL_CENTERLINES],
            "is_main": [c[1] for c in LABEL_CENTERLINES],
        },
        geometry=[shapely.LineString(c[2]) for c in LABEL_CENTERLINES],
        crs="EPSG:4326",
    ).to_parquet(out, index=False)
    return out


@pytest.fixture(scope="module")
def labels_parquet(glaciers_parquet: Path, label_centerlines_parquet: Path) -> Path:
    return write_labels(
        glaciers_parquet,
        label_centerlines_parquet,
        glaciers_parquet.parent / "glacier-labels.parquet",
    )


@pytest.fixture(scope="module")
def label_bands(labels_parquet: Path) -> dict[int, Path]:
    return tiles.write_label_bands(labels_parquet, labels_parquet.parent / "glacier-labels")


@pytest.fixture(scope="module")
def label_points(labels_parquet: Path) -> Path:
    return tiles.write_label_points(labels_parquet, labels_parquet.parent / "label-points.parquet")


@pytest.fixture(scope="module")
def overview(glaciers_parquet: Path) -> dict[int, Path]:
    out = glaciers_parquet.parent / "overview"
    return tiles.write_overview(glaciers_parquet, out, tiles.GLACIER_OVERVIEW_COLUMNS)


@pytest.fixture(scope="module")
def archive(
    glaciers_parquet: Path,
    label_bands: dict[int, Path],
    label_points: Path,
    overview: dict[int, Path],
) -> Path:
    return build_archive(
        glacier_layers(glaciers_parquet, label_bands, label_points, overview),
        glaciers_parquet.parent / "rgi7.0.pmtiles",
        name=tiles.ARCHIVE_NAME,
        attribution=tiles.ARCHIVE_ATTRIBUTION,
        description="Test archive.",
    )


def test_label_minzoom_monotonic() -> None:
    areas = [0.01, 0.2, 1, 8, 25, 82, 1000]
    zooms = [label_minzoom(a) for a in areas]
    assert zooms == sorted(zooms, reverse=True)
    assert label_minzoom(82) <= 8
    assert label_minzoom(0.2) >= 12
    assert all(tiles.LABEL_MINZOOM <= z <= tiles.MAXZOOM for z in zooms)


def test_write_labels_skips_unnamed_and_uses_rgi_point(labels_parquet: Path) -> None:
    labels = gpd.read_parquet(labels_parquet)
    labels = labels.loc[labels.geom_type == "Point"]
    named = [g for g in GLACIERS if g[4] is not None]
    assert sorted(labels["rgi_id"]) == sorted(g[0] for g in named)
    assert list(labels.columns) == [
        "rgi_id",
        "display_name",
        "area_km2",
        "label_minzoom",
        "line_zoom",
        "label_zoom",
        "geometry",
    ]
    for rgi_id, lon, lat, area, name in named:
        row = labels.loc[labels["rgi_id"] == rgi_id].iloc[0]
        assert row["geometry"].x == lon
        assert row["geometry"].y == lat
        assert row["display_name"] == name
        assert row["label_minzoom"] == label_minzoom(area)
        assert pd.isna(row["label_zoom"])


def test_write_labels_adds_line_per_zoom_along_longest_main_centerline(
    labels_parquet: Path,
) -> None:
    labels = gpd.read_parquet(labels_parquet)
    lines = labels.loc[labels.geom_type == "LineString"]
    assert set(lines["rgi_id"]) == {BIG}
    point = labels.loc[(labels["rgi_id"] == BIG) & (labels.geom_type == "Point")].iloc[0]
    assert point["line_zoom"] >= point["label_minzoom"]
    assert list(lines["label_zoom"]) == list(range(point["line_zoom"], tiles.LABEL_MAXZOOM + 1))
    assert (lines["label_minzoom"] == lines["label_zoom"]).all()
    assert (lines["line_zoom"] == point["line_zoom"]).all()
    assert (lines["display_name"] == point["display_name"]).all()
    line = lines.iloc[0]
    # The longer main line, not the shorter one at 61.1. At its line_zoom the
    # line is shorter than a stretch, so the label line is all of it.
    assert line["geometry"].bounds[1] == pytest.approx(61.0, abs=0.001)
    assert line["geometry"].centroid.x == pytest.approx(-147.0, abs=0.01)
    # The line runs east to its terminus. At each later zoom the name sits
    # further down the line.
    middles = [g.interpolate(0.5, normalized=True).x for g in lines["geometry"]]
    assert middles == sorted(middles)
    assert middles[-1] > middles[0]
    short = labels.loc[labels["rgi_id"] == "RGI2000-v7.0-G-11-00001"]
    assert list(short.geom_type) == ["Point"]
    assert pd.isna(short["line_zoom"].iloc[0])


def test_center_label_fits_refuses_sharp_corner() -> None:
    straight = np.array([[0.0, 0.0], [200.0, 0.0]])
    corner = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 100.0]])
    arc = np.array([[100 * np.cos(t), 100 * np.sin(t)] for t in np.linspace(0, 1, 50)])
    assert tiles.center_label_fits(straight, 100)
    assert not tiles.center_label_fits(corner, 100)
    assert tiles.center_label_fits(arc, 80)
    assert not tiles.center_label_fits(straight, 300)


def test_center_label_fits_takes_maplibre_limit() -> None:
    # A corner of 42° passes MapLibre's 45° but not the fit's 40°.
    turn = math.radians(42)
    corner = np.array(
        [[0.0, 0.0], [100.0, 0.0], [100 + 100 * math.cos(turn), 100 * math.sin(turn)]]
    )
    assert not tiles.center_label_fits(corner, 100)
    assert tiles.center_label_fits(corner, 100, max_angle=math.radians(45))


def test_center_label_fits_sums_corners_in_window() -> None:
    # Three corners of 20° within 6 px turn 60° in one window of 7.2 px.
    # Spread 10 px apart, each window holds one corner.
    def zigzag(step: float) -> np.ndarray:
        heading = np.radians([0, 20, 40, 60, 60])
        lengths = [100, step, step, step, 100]
        moves = np.column_stack([np.cos(heading), np.sin(heading)]) * np.array(lengths)[:, None]
        return np.vstack([[0, 0], np.cumsum(moves, axis=0)])

    assert not tiles.center_label_fits(zigzag(3.0), 100)
    assert tiles.center_label_fits(zigzag(10.0), 100)


def test_label_width_px_shapes_like_maplibre() -> None:
    advances = glyphs.load_advances()
    scale = tiles.LABEL_TEXT_SIZE / glyphs.GLYPH_PX
    spacing = tiles.LABEL_LETTER_SPACING * tiles.LABEL_TEXT_SIZE
    expected = (advances[ord("A")] + advances[ord("b")]) * scale + spacing
    assert tiles.label_width_px("Ab") == pytest.approx(expected)
    assert tiles.label_width_px("") == 0


def test_tile_grid_rounds_to_eighth_pixel_and_drops_repeats() -> None:
    line = np.array([[0.01, 0.0], [0.02, 0.0], [10.06, 5.0]])
    assert tiles.tile_grid(line, tiles.MAXZOOM).tolist() == [[0.0, 0.0], [10.0, 5.0]]
    # Two zooms past MAXZOOM the line is in a MAXZOOM tile, on a 1/2 pixel grid.
    line = np.array([[0.2, 0.0], [10.3, 5.2]])
    zoom = tiles.MAXZOOM + 2
    assert tiles.tile_grid(line, zoom).tolist() == [[0.0, 0.0], [10.5, 5.0]]


def test_smooth_line_keeps_ends_and_rounds_corners() -> None:
    # A corner of 45° turns too far for a label, and the smoothing spreads it.
    corner = np.array([[0.0, 0.0], [100.0, 0.0], [170.7, 70.7]])
    smoothed = tiles.smooth_line(corner, tiles.LABEL_SMOOTH_PX)
    assert smoothed[0] == pytest.approx([0, 0], abs=1e-6)
    assert smoothed[-1] == pytest.approx(corner[-1], abs=1e-6)
    assert not tiles.center_label_fits(corner, 100)
    assert tiles.center_label_fits(smoothed, 100)


def test_tile_properties_leaves_out_list_columns(glaciers_parquet: Path) -> None:
    assert tile_properties(glaciers_parquet) == [
        "rgi_id",
        "o1region",
        "cenlon",
        "cenlat",
        "area_km2",
        "term_type",
        "display_name",
    ]


def test_build_archive_contains_layers(archive: Path) -> None:
    with archive.open("rb") as f:
        reader = Reader(MmapSource(f))
        header = reader.header()
        meta = reader.metadata()
    layers = {layer["id"]: layer for layer in meta["vector_layers"]}
    assert set(layers) == {"glaciers", "glacier-labels", "glacier-label-points"}
    assert "label_minzoom" not in layers["glacier-labels"]["fields"]
    assert "label_zoom" not in layers["glacier-label-points"]["fields"]
    assert meta["name"] == tiles.ARCHIVE_NAME
    assert meta["attribution"] == tiles.ARCHIVE_ATTRIBUTION
    assert meta["description"] == "Test archive."
    west, south = header["min_lon_e7"] / 1e7, header["min_lat_e7"] / 1e7
    east, north = header["max_lon_e7"] / 1e7, header["max_lat_e7"] / 1e7
    assert -180 <= west <= east <= 180
    assert -90 <= south <= north <= 90
    assert east >= 179.95
    assert west <= 10.75
    glacier_fields = next(x for x in meta["vector_layers"] if x["id"] == "glaciers")["fields"]
    assert "hypso_permille" not in glacier_fields
    assert "rgi6_links" not in glacier_fields
    assert "bbox" not in glacier_fields


def test_build_archive_label_points_enter_at_their_zoom(archive: Path, tmp_path: Path) -> None:
    decoded = decode(archive, tmp_path / "labels.parquet", layer="glacier-label-points")
    rows = pq.read_table(decoded, columns=["rgi_id", "zoom"]).to_pandas()
    zooms = {k: sorted(set(v)) for k, v in rows.groupby("rgi_id")["zoom"]}
    for rgi_id, _, _, area, name in GLACIERS:
        if name is None:
            assert rgi_id not in zooms
            continue
        assert zooms[rgi_id] == list(range(label_minzoom(area), tiles.MAXZOOM + 1))


def test_build_archive_label_line_only_at_its_zoom(
    archive: Path, labels_parquet: Path, tmp_path: Path
) -> None:
    lines = gpd.read_parquet(decode(archive, tmp_path / "l.parquet", layer="glacier-labels"))
    assert lines.geom_type.isin(["LineString", "MultiLineString"]).all()
    source = gpd.read_parquet(labels_parquet)
    line_zoom = int(source.loc[source.geom_type == "LineString", "line_zoom"].iloc[0])
    assert set(lines["rgi_id"]) == {BIG}
    assert sorted(set(lines["zoom"])) == list(range(line_zoom, tiles.MAXZOOM + 1))
    past = lines["zoom"] == tiles.MAXZOOM
    assert (lines.loc[~past, "label_zoom"] == lines.loc[~past, "zoom"]).all()
    # The MAXZOOM tiles also hold the lines of the zooms past it.
    assert sorted(set(lines.loc[past, "label_zoom"])) == list(
        range(tiles.MAXZOOM, tiles.LABEL_MAXZOOM + 1)
    )


def test_write_label_bands_holds_own_lines(
    labels_parquet: Path, label_bands: dict[int, Path]
) -> None:
    labels = gpd.read_parquet(labels_parquet)
    line_zoom = int(labels["label_zoom"].min())
    # A zoom without a line has no band.
    assert sorted(label_bands) == list(range(line_zoom, tiles.MAXZOOM + 1))
    for zoom, path in label_bands.items():
        band = gpd.read_parquet(path)
        assert (band.geom_type == "LineString").all()
        assert "label_minzoom" not in band.columns
        own = labels["label_zoom"] == zoom
        if zoom == tiles.MAXZOOM:
            own = labels["label_zoom"] >= zoom
        assert set(band["label_zoom"]) == set(labels.loc[own, "label_zoom"])
        assert len(band) == own.sum()


def test_write_label_points_holds_every_point(labels_parquet: Path, label_points: Path) -> None:
    labels = gpd.read_parquet(labels_parquet)
    points = gpd.read_parquet(label_points)
    assert (points.geom_type == "Point").all()
    assert sorted(points["rgi_id"]) == sorted(labels.loc[labels["label_zoom"].isna(), "rgi_id"])
    assert "label_zoom" not in points.columns


def test_build_archive_glaciers_complete_from_complete_zoom(
    archive: Path,
    tmp_path: Path,
) -> None:
    decoded = decode(archive, tmp_path / "glaciers.parquet", layer="glaciers")
    rows = pq.read_table(decoded, columns=["rgi_id", "zoom"]).to_pandas()
    counts = rows.groupby("zoom")["rgi_id"].nunique()
    for zoom in range(tiles.GLACIERS_COMPLETE_ZOOM, tiles.MAXZOOM + 1):
        assert counts[zoom] == len(GLACIERS)


def _shape_zooms() -> dict[str, int]:
    frame = _glaciers_frame()
    bounds = frame.to_crs(3857).bounds
    extent = np.maximum(
        (bounds["maxx"] - bounds["minx"]).to_numpy(), (bounds["maxy"] - bounds["miny"]).to_numpy()
    )
    zooms = tiles.shape_minzoom(extent)
    return dict(zip(frame["rgi_id"], (int(z) for z in zooms), strict=True))


def test_shape_minzoom() -> None:
    px = tiles.SHAPE_MIN_PX * tiles.pixel_m(0)
    extents = np.array([px, px * 0.99, px / 2**5, 1.0])
    assert tiles.shape_minzoom(extents).tolist() == [0, 1, 5, tiles.GLACIERS_COMPLETE_ZOOM]


def test_write_overview_shapes_large_glaciers_only(
    glaciers_parquet: Path,
    overview: dict[int, Path],
) -> None:
    shape_zooms = _shape_zooms()
    assert 0 < shape_zooms[BIG] < min(z for k, z in shape_zooms.items() if k != BIG)
    assert sorted(overview) == list(range(tiles.GLACIERS_COMPLETE_ZOOM))
    for zoom, path in overview.items():
        rows = gpd.read_parquet(path)
        assert len(rows) == len(GLACIERS)
        assert [c for c in rows.columns if c != "geometry"] == [
            c for c in tiles.GLACIER_OVERVIEW_COLUMNS if c in tile_properties(glaciers_parquet)
        ]
        for rgi_id, lon, lat, _, _ in GLACIERS:
            geom = rows.loc[rows["rgi_id"] == rgi_id].geometry.iloc[0]
            if zoom >= shape_zooms[rgi_id]:
                assert geom.geom_type == "Polygon", (rgi_id, zoom)
            else:
                # A glacier too small to draw is RGI's point (cenlon, cenlat).
                assert (geom.geom_type, geom.x, geom.y) == ("Point", lon, lat), zoom


def test_build_archive_draws_large_glaciers_as_shapes(archive: Path, tmp_path: Path) -> None:
    decoded = gpd.read_parquet(decode(archive, tmp_path / "low.parquet", layer="glaciers"))
    shape_zooms = _shape_zooms()
    # A glacier at the antimeridian is a MultiPoint where the buffer wraps.
    points = {"Point", "MultiPoint"}
    for (rgi_id, zoom), rows in decoded.groupby(["rgi_id", "zoom"]):
        is_point = set(rows.geom_type) <= points
        assert is_point == (zoom < shape_zooms[rgi_id]), (rgi_id, zoom)
    # Every outline is kept, and the big glacier is in every zoom.
    big_zooms = set(decoded.loc[decoded["rgi_id"] == BIG, "zoom"])
    assert big_zooms == set(range(tiles.MAXZOOM + 1))


def test_archive_attribution_names_the_producer() -> None:
    assert tiles.ARCHIVE_ATTRIBUTION == "RGI 7.0 Consortium (2023)"


def test_archive_is_shared_by_the_version() -> None:
    assert tiles.archive_path(Path("staging"), "7.0") == Path("staging/v7.0/rgi7.0.pmtiles")


def test_build_archive_refuses_drop_in_complete_band(
    glaciers_parquet: Path,
    tmp_path: Path,
) -> None:
    # A 1-byte tile cap forces the tiler to drop features.
    layer = LayerSpec(
        name="glaciers",
        source=glaciers_parquet,
        minzoom=10,
        maxzoom=10,
        extra_args=("--no-density-drop", "--max-tile-size", "1"),
        complete=True,
    )
    with pytest.raises(tiles.TileDropError, match="glaciers"):
        build_archive([layer], tmp_path / "out.pmtiles", **META)
    assert not (tmp_path / "out.pmtiles").exists()


def test_build_archive_refuses_thinned_complete_band(
    glaciers_parquet: Path,
    tmp_path: Path,
) -> None:
    # At z0 the three Alpine glaciers share one thinning cell, so default
    # thinning keeps one of them. The report shows no oversized tile.
    layer = LayerSpec(
        name="glaciers",
        source=glaciers_parquet,
        minzoom=0,
        maxzoom=10,
        extra_args=("--polygon-visibility", "0"),
        complete=True,
    )
    with pytest.raises(tiles.TileDropError, match="z0"):
        build_archive([layer], tmp_path / "out.pmtiles", **META)


def test_build_archive_accepts_entry_zoom_band(labels_parquet: Path, tmp_path: Path) -> None:
    # Labels enter at their own zoom. A complete band is checked against the
    # labels that have entered, not against every label.
    entry = ",".join(f"{z}={z}" for z in range(tiles.LABEL_MINZOOM, tiles.MAXZOOM + 1))
    labels = gpd.read_parquet(labels_parquet)
    points = tmp_path / "points.parquet"
    labels.loc[labels["label_zoom"].isna()].to_parquet(points, index=False)
    layer = LayerSpec(
        name="glacier-labels",
        source=points,
        minzoom=tiles.LABEL_MINZOOM,
        maxzoom=tiles.MAXZOOM,
        extra_args=("--entry-zoom", f"label_minzoom:{entry}", *tiles.LINE_COMPLETE),
        complete=True,
        entry_zoom_column="label_minzoom",
    )
    out = build_archive([layer], tmp_path / "out.pmtiles", **META)
    assert out.exists()


def test_set_metadata_keeps_tiles(archive: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy.pmtiles"
    copy.write_bytes(archive.read_bytes())
    tiles.set_metadata(copy, {"description": "Changed."})
    with archive.open("rb") as a, copy.open("rb") as b:
        old, new = Reader(MmapSource(a)), Reader(MmapSource(b))
        assert new.metadata()["description"] == "Changed."
        assert new.metadata()["vector_layers"] == old.metadata()["vector_layers"]
        assert list(all_tiles(new.get_bytes)) == list(all_tiles(old.get_bytes))
        old_header = {k: v for k, v in old.header().items() if "offset" not in k}
        new_header = {k: v for k, v in new.header().items() if "offset" not in k}
        old_header.pop("metadata_length")
        new_header.pop("metadata_length")
        assert new_header == old_header


def test_write_region_labels_one_per_region(fake_rgi: FakeRGI, tmp_path: Path) -> None:
    regions, _ = assemble.regions(fake_rgi.regions_zip)
    source = tmp_path / "regions.parquet"
    regions.to_parquet(source)
    labels = gpd.read_parquet(tiles.write_region_labels(source, tmp_path / "labels.parquet"))
    assert list(labels.columns) == ["level", "o1region", "o2region", "full_name", "geometry"]
    assert sorted(zip(labels["level"], labels["full_name"], strict=True)) == [
        (1, "Central Europe"),
        (1, "North Asia"),
        (1, "Scandinavia"),
        (2, "Alps"),
        (2, "Sør-Norge"),
    ]
    for _, label in labels.iterrows():
        same = regions[(regions["level"] == label["level"])]
        same = same[same["full_name"] == label["full_name"]]
        assert same.geometry.contains(label.geometry).any()
    # Region 10 is one row of two pieces. Its label sits in the larger one.
    north_asia = labels.loc[labels["full_name"] == "North Asia"].geometry.iloc[0]
    assert 170 < north_asia.x < 180


def test_write_region_boundaries_draws_each_border_once(tmp_path: Path) -> None:
    def box(x0: float, y0: float, x1: float, y1: float) -> Polygon:
        return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    rows = [
        # Two first-order regions. The west one splits their border at (2, 1).
        (1, Polygon([(0, 0), (2, 0), (2, 1), (2, 2), (0, 2)])),
        (1, box(2, 0, 4, 2)),
        # One first-order region split at the antimeridian. Its parts are
        # second-order regions that border each other there.
        (1, MultiPolygon([box(170, 10, 180, 20), box(-180, 10, -170, 20)])),
        # A first-order region whose outer edge lies on the antimeridian.
        (1, box(-180, 30, -175, 35)),
        # A first-order region around the South Pole, closed at -90.
        (1, box(-180, -90, 180, -80)),
        (2, box(0, 0, 1, 2)),
        # The edge at x = 2 is split at (2, 0.5), not at (2, 1).
        (2, Polygon([(1, 0), (2, 0), (2, 0.5), (2, 2), (1, 2)])),
        (2, box(2, 0, 4, 2)),
        (2, box(170, 10, 180, 20)),
        (2, box(-180, 10, -170, 20)),
    ]
    regions = gpd.GeoDataFrame(
        {"level": np.array([level for level, _ in rows], dtype=np.uint8)},
        geometry=[geom for _, geom in rows],
        crs="OGC:CRS84",
    )
    regions.to_parquet(tmp_path / "regions.parquet")
    out = tiles.write_region_boundaries(tmp_path / "regions.parquet", tmp_path / "b.parquet")
    boundaries = gpd.read_parquet(out)

    assert list(boundaries.columns) == ["level", "geometry"]
    assert set(boundaries.geom_type) == {"LineString"}
    lengths = pd.Series(shapely.length(boundaries.geometry.to_numpy()))
    by_level = lengths.groupby(boundaries["level"]).sum()
    # Level 1: the outline of both squares and their border (14), the
    # antimeridian region without its cut (60), the region at -180 (20), the
    # polar region without its cut and its edge at the pole (360).
    # Level 2: the border at x = 1 (2) and the border at the antimeridian (10).
    assert by_level.to_dict() == pytest.approx({1: 454.0, 2: 12.0})
    # No border is stored twice.
    assert shapely.union_all(boundaries.geometry.to_numpy()).length == pytest.approx(466.0)
    # The border at the antimeridian is kept at 180 only.
    west = shapely.intersection(
        shapely.union_all(boundaries.geometry.to_numpy()),
        shapely.LineString([(-180, -90), (-180, 90)]),
    )
    assert west.length == pytest.approx(5.0)
    # Contiguous edges are one line: the region at -180 is one closed ring.
    assert np.isclose(lengths, 20.0).sum() == 1


def test_span_minzoom_per_feature_maxzoom() -> None:
    px = 32 * tiles.pixel_m(5)
    extents = np.array([px, px, px / 2**10, px / 2**10])
    zooms = tiles.span_minzoom(extents, 32, 4, np.array([8, 4, 8, 9]))
    assert zooms.tolist() == [5, 4, 8, 9]


def _degrees(metres: float) -> float:
    """Return the longitude span of a distance at the equator."""
    return metres / tiles.WORLD_M * 360


# (rgi_id, is_main, zoom). Each line runs east along the equator. It spans
# a little more than LINE_MIN_PX pixels at its zoom.
EARLY_LINES = [
    ("z5", False, 5),
    ("z7", True, 7),
    ("z3", True, 3),
    ("short-main", True, 12),
    ("short", False, 12),
]


@pytest.fixture
def centerlines_parquet(tmp_path: Path) -> Path:
    lines = gpd.GeoDataFrame(
        {"rgi_id": [r[0] for r in EARLY_LINES], "is_main": [r[1] for r in EARLY_LINES]},
        geometry=[
            shapely.LineString(
                [(0, 0), (_degrees(1.01 * tiles.LINE_MIN_PX * tiles.pixel_m(z)), 0)]
            )
            for _, _, z in EARLY_LINES
        ],
        crs="OGC:CRS84",
    )
    lines.to_parquet(tmp_path / "c.parquet")
    return tmp_path / "c.parquet"


def test_write_early_lines_enters_long_lines_first(
    centerlines_parquet: Path, tmp_path: Path
) -> None:
    early = gpd.read_parquet(tiles.write_early_lines(centerlines_parquet, tmp_path / "e.parquet"))
    zooms = dict(zip(early["rgi_id"], early["line_minzoom"], strict=True))
    # A short line that is not a main centerline enters with the full band.
    assert zooms == {
        "z5": 5,
        "z7": 7,
        "z3": tiles.LINES_MINZOOM,
        "short-main": tiles.CENTERLINES_MINZOOM,
    }
    divides = gpd.read_parquet(centerlines_parquet).drop(columns="is_main")
    divides.to_parquet(tmp_path / "i.parquet")
    early = gpd.read_parquet(
        tiles.write_early_lines(tmp_path / "i.parquet", tmp_path / "f.parquet")
    )
    assert sorted(early["rgi_id"]) == ["z3", "z5", "z7"]


def test_build_archive_early_centerlines_enter_at_their_zoom(
    centerlines_parquet: Path, tmp_path: Path
) -> None:
    early = tiles.write_early_lines(centerlines_parquet, tmp_path / "e.parquet")
    layers = tiles.version_layers(
        dict.fromkeys(tiles.ARCHIVE_PRODUCTS, centerlines_parquet),
        {tiles.MAXZOOM: tmp_path / "labels.parquet"},
        tmp_path / "lp.parquet",
        tmp_path / "rl.parquet",
        tmp_path / "rb.parquet",
        {"centerlines": early, "intersects": early},
        {name: {} for name in tiles.OVERVIEW_COLUMNS},
    )
    bands = [b for b in layers if b.name == "centerlines" and b.maxzoom < tiles.INTERSECTS_MINZOOM]
    archive = build_archive(bands, tmp_path / "out.pmtiles", **META)
    rows = pq.read_table(decode(archive, tmp_path / "d.parquet"), columns=["rgi_id", "zoom"])
    zooms = {k: sorted(set(v)) for k, v in rows.to_pandas().groupby("rgi_id")["zoom"]}
    # The last zoom of a band keeps every source feature unless the band
    # filters out the lines that enter after it.
    eight = tiles.CENTERLINES_MINZOOM
    assert zooms == {
        "z5": list(range(5, eight + 1)),
        "z7": [7, eight],
        "z3": list(range(tiles.LINES_MINZOOM, eight + 1)),
        "short-main": [eight],
    }


def test_build_archive_simplifies_in_map_units_at_high_latitude(tmp_path: Path) -> None:
    # A square at 78°N with a bump of 1.5 pixels at z9 on its north edge.
    # The tolerance at --simplify-factor 1 is half a pixel, so the bump
    # stays. A tolerance in degrees would be 2.5 pixels there. The finest
    # zoom of a tiling is not simplified, so the band is padded.
    zoom = 9
    lon, lat = 0.35, 78.0
    side = 0.2
    bump = 1.5 * tiles.pixel_m(zoom)
    north = gpd.GeoSeries([shapely.Point(lon, lat + side)], crs="EPSG:4326").to_crs(3857)
    bumped = gpd.GeoSeries(
        [shapely.Point(north.x.iloc[0], north.y.iloc[0] + bump)], crs=3857
    ).to_crs(4326)
    square = shapely.Polygon(
        [
            (lon - side, lat),
            (lon + side, lat),
            (lon + side, lat + side),
            (lon, bumped.y.iloc[0]),
            (lon - side, lat + side),
        ]
    )
    source = tmp_path / "g.parquet"
    gpd.GeoDataFrame({"rgi_id": ["a"]}, geometry=[square], crs="EPSG:4326").to_parquet(source)
    layer = LayerSpec(
        "glaciers",
        source,
        zoom,
        zoom,
        (
            "--no-density-drop",
            "--polygon-thinning",
            "0",
            "--polygon-visibility",
            "0",
            "--simplify-factor",
            "1",
        ),
        complete=True,
        pad_zoom=1,
    )
    archive = build_archive([layer], tmp_path / "out.pmtiles", **META)
    decoded = gpd.read_parquet(decode(archive, tmp_path / "d.parquet")).to_crs(3857)
    top = max(shapely.get_coordinates(decoded.geometry.to_numpy())[:, 1])
    assert top == pytest.approx(north.y.iloc[0] + bump, abs=tiles.pixel_m(zoom) / 4)


def test_write_web_mercator_cuts_off_the_poles(tmp_path: Path) -> None:
    region = shapely.box(-180, -90, 180, -60)
    source = tmp_path / "r.parquet"
    gpd.GeoDataFrame({"level": [1]}, geometry=[region], crs="OGC:CRS84").to_parquet(source)
    out = gpd.read_parquet(tiles.write_web_mercator(source, tmp_path / "m.parquet", ["level"]))
    assert out.crs.to_epsg() == 3857
    _, south, _, north = out.total_bounds
    assert south == pytest.approx(-tiles.WORLD_M / 2)
    assert north < 0


def test_version_layers_cover_every_product(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{name}.parquet" for name in tiles.ARCHIVE_PRODUCTS}
    early = {name: tmp_path / f"early-{name}.parquet" for name in ("centerlines", "intersects")}
    zooms = range(tiles.GLACIERS_COMPLETE_ZOOM)
    overviews = {
        name: {z: tmp_path / f"{name}-z{z}.parquet" for z in zooms}
        for name in tiles.OVERVIEW_COLUMNS
    }
    layers = tiles.version_layers(
        paths,
        {
            z: tmp_path / f"labels-{z}.parquet"
            for z in range(tiles.LABEL_MINZOOM, tiles.MAXZOOM + 1)
        },
        tmp_path / "lp.parquet",
        tmp_path / "rl.parquet",
        tmp_path / "rb.parquet",
        early,
        overviews,
    )
    assert {layer.name for layer in layers} == {
        "regions",
        "region-boundaries",
        "region-labels",
        "complexes",
        "glaciers",
        "glacier-labels",
        "glacier-label-points",
        "centerlines",
        "intersects",
    }
    complete = {(layer.name, layer.minzoom, layer.maxzoom) for layer in layers if layer.complete}
    assert complete >= {
        ("regions", 0, tiles.MAXZOOM),
        ("region-boundaries", 0, tiles.MAXZOOM),
        ("region-labels", 0, tiles.MAXZOOM),
        ("complexes", tiles.GLACIERS_COMPLETE_ZOOM, tiles.MAXZOOM),
        ("glaciers", tiles.GLACIERS_COMPLETE_ZOOM, tiles.MAXZOOM),
        ("centerlines", tiles.INTERSECTS_MINZOOM, tiles.INTERSECTS_MINZOOM),
        ("centerlines", tiles.INTERSECTS_MINZOOM + 1, tiles.MAXZOOM),
        ("intersects", tiles.INTERSECTS_MINZOOM, tiles.MAXZOOM),
        *(("glacier-labels", z, z) for z in range(tiles.LABEL_MINZOOM, tiles.MAXZOOM + 1)),
        ("glacier-label-points", tiles.LABEL_MINZOOM, tiles.MAXZOOM),
    }
    # Only the label lines need a buffer of a whole tile.
    points = next(layer for layer in layers if layer.name == "glacier-label-points")
    assert "--tile-buffer" not in points.extra_args
    # The early lines enter at their own zoom, and the main centerlines and
    # the long lines fill z8. From z9 every line is in the archive.
    bands = {
        name: [(b.minzoom, b.maxzoom, b.entry_zoom_column) for b in layers if b.source == path]
        for name, path in early.items()
    }
    first = tiles.LINES_MINZOOM
    assert bands == {
        "centerlines": [
            (first, tiles.CENTERLINES_MINZOOM - 1, "line_minzoom"),
            (tiles.CENTERLINES_MINZOOM, tiles.CENTERLINES_MINZOOM, None),
        ],
        "intersects": [(first, tiles.INTERSECTS_MINZOOM - 1, "line_minzoom")],
    }
    for layer in layers:
        if layer.name in {"region-boundaries", "centerlines", "intersects"} and layer.complete:
            assert "--no-coalesce-lines" in layer.extra_args
    # One overview band per zoom, tiled a zoom further so that its own zoom
    # is thinned.
    for name, inputs in overviews.items():
        bands = [layer for layer in layers if layer.source in inputs.values()]
        assert [(b.minzoom, b.maxzoom, b.pad_zoom) for b in bands] == [(z, z, 1) for z in zooms]
        assert all(b.name == name for b in bands)


def test_build_archive_overview_carries_style_columns_only(
    archive: Path,
    tmp_path: Path,
) -> None:
    decoded = pq.read_table(decode(archive, tmp_path / "g.parquet", layer="glaciers")).to_pandas()
    overview = decoded[decoded["zoom"] < tiles.GLACIERS_COMPLETE_ZOOM]
    complete = decoded[decoded["zoom"] >= tiles.GLACIERS_COMPLETE_ZOOM]
    assert overview["o1region"].isna().all()
    assert overview["rgi_id"].notna().all()
    assert overview["area_km2"].notna().all()
    assert complete["o1region"].notna().all()


def test_overview_columns_cover_the_styles() -> None:
    themed = {theme.column for theme in styles.THEMES.values()}
    assert themed | {"rgi_id", "display_name", "area_km2"} <= set(tiles.GLACIER_OVERVIEW_COLUMNS)
    assert set(tiles.COMPLEX_OVERVIEW_COLUMNS) == {"rgi_id", "area_km2"}


def test_stretch_starts_slide_up_from_terminus_margin() -> None:
    # The name ends a tenth of the line before the terminus. The slide
    # goes up to the head and passes the middle.
    line_px, label_px, keep_px = 1000.0, 92.0, 160.0
    starts = tiles.stretch_starts(line_px, label_px, keep_px)
    label_end = starts[0] + (keep_px + label_px) / 2
    assert label_end == pytest.approx(line_px * (1 - tiles.LABEL_TONGUE_MARGIN))
    assert np.all(np.diff(starts) < 0)
    assert np.all(-np.diff(starts) <= tiles.LABEL_SLIDE_PX)
    assert (line_px - keep_px) / 2 in starts
    assert starts[-1] == 0
    # A name that only fits at the middle keeps the middle.
    assert tiles.stretch_starts(200.0, 150.0, 200.0).tolist() == [0.0]


def _metres(outline: shapely.Geometry, zoom: int) -> shapely.Geometry:
    return shapely.transform(outline, lambda xy: xy * tiles.pixel_m(zoom))


def test_label_line_sits_near_terminus_before_a_bend() -> None:
    zoom = tiles.MAXZOOM
    px_m = tiles.pixel_m(zoom)
    label_px = tiles.label_width_px("Big Glacier")
    needed_px = label_px + 2 * tiles.LABEL_PAD_PX
    # The line runs from the head at x = 0 to the terminus at x = 1000.
    straight = np.array([[0.0, 0.0], [1000.0, 0.0]])
    wide = shapely.box(-100.0, -500.0, 1100.0, 500.0)
    placed = tiles.label_window(straight * px_m, "Big Glacier", zoom, _metres(wide, zoom))
    assert placed is not None
    center = shapely.LineString(placed / tiles.pixel_m(zoom)).interpolate(0.5, normalized=True)
    margin = 1000 * tiles.LABEL_TONGUE_MARGIN
    assert center.x + label_px / 2 == pytest.approx(1000 - margin, abs=0.5)
    # A sharp bend near the terminus pushes the name up the line, past the bend.
    bent = np.array([[0.0, 0.0], [600.0, 0.0], [600.0, -60.0]])
    placed = tiles.label_window(bent * px_m, "Big Glacier", zoom, _metres(wide, zoom))
    assert placed is not None
    center = shapely.LineString(placed / tiles.pixel_m(zoom)).interpolate(0.5, normalized=True)
    assert 600 - needed_px / 2 - 4 * tiles.LABEL_SMOOTH_PX < center.x < 600 - needed_px / 2


def test_label_line_keeps_clear_of_a_narrow_tongue() -> None:
    zoom = tiles.MAXZOOM
    px_m = tiles.pixel_m(zoom)
    label_px = tiles.label_width_px("Big Glacier")
    line = np.array([[0.0, 0.0], [1000.0, 0.0]])
    # The glacier is 100 px wide up to x = 600 and 16 px wide below it.
    half = 8.0
    tongue = shapely.box(0.0, -50.0, 600.0, 50.0) | shapely.box(600.0, -half, 1000.0, half)
    placed = tiles.label_window(line * px_m, "Big Glacier", zoom, _metres(tongue, zoom))
    assert placed is not None
    center = shapely.LineString(placed / px_m).interpolate(0.5, normalized=True)
    # The text ends where it keeps LABEL_CLEARANCE_PX to the corner at (600, 8).
    limit = 600 - math.sqrt(tiles.LABEL_CLEARANCE_PX**2 - half**2)
    assert limit - tiles.LABEL_SLIDE_PX - 0.5 <= center.x + label_px / 2 <= limit + 0.5
    # A glacier narrower than the text everywhere gets no line.
    strip = shapely.box(-100.0, -half, 1100.0, half)
    assert tiles.label_window(line * px_m, "Big Glacier", zoom, _metres(strip, zoom)) is None
