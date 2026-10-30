"""Tests for the web-map archive."""

from __future__ import annotations

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

from rgi_catalog import assemble, styles, tiles
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


@pytest.fixture(scope="module")
def labels_parquet(glaciers_parquet: Path) -> Path:
    return write_labels(glaciers_parquet, glaciers_parquet.parent / "glacier-labels.parquet")


@pytest.fixture(scope="module")
def overview(glaciers_parquet: Path) -> dict[int, Path]:
    out = glaciers_parquet.parent / "overview"
    return tiles.write_overview(glaciers_parquet, out, tiles.GLACIER_OVERVIEW_COLUMNS)


@pytest.fixture(scope="module")
def archive(glaciers_parquet: Path, labels_parquet: Path, overview: dict[int, Path]) -> Path:
    return build_archive(
        glacier_layers(glaciers_parquet, labels_parquet, overview),
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
    named = [g for g in GLACIERS if g[4] is not None]
    assert sorted(labels["rgi_id"]) == sorted(g[0] for g in named)
    assert list(labels.columns) == [
        "rgi_id",
        "display_name",
        "area_km2",
        "label_minzoom",
        "geometry",
    ]
    for rgi_id, lon, lat, area, name in named:
        row = labels.loc[labels["rgi_id"] == rgi_id].iloc[0]
        assert row["geometry"].x == lon
        assert row["geometry"].y == lat
        assert row["display_name"] == name
        assert row["label_minzoom"] == label_minzoom(area)


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
    assert {layer["id"] for layer in meta["vector_layers"]} == {"glaciers", "glacier-labels"}
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


def test_build_archive_label_entry_zoom(archive: Path, tmp_path: Path) -> None:
    decoded = decode(archive, tmp_path / "labels.parquet", layer="glacier-labels")
    rows = pq.read_table(decoded, columns=["rgi_id", "zoom"]).to_pandas()
    zooms = {k: sorted(set(v)) for k, v in rows.groupby("rgi_id")["zoom"]}
    for rgi_id, _, _, area, name in GLACIERS:
        if name is None:
            assert rgi_id not in zooms
            continue
        assert zooms[rgi_id] == list(range(label_minzoom(area), tiles.MAXZOOM + 1))


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
    layer = LayerSpec(
        name="glacier-labels",
        source=labels_parquet,
        minzoom=tiles.LABEL_MINZOOM,
        maxzoom=tiles.MAXZOOM,
        extra_args=("--entry-zoom", f"label_minzoom:{entry}", "--no-density-drop"),
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
    # antimeridian region without its cut (60), the region at -180 (20).
    # Level 2: the border at x = 1 (2) and the border at the antimeridian (10).
    assert by_level.to_dict() == pytest.approx({1: 94.0, 2: 12.0})
    # No border is stored twice.
    assert shapely.union_all(boundaries.geometry.to_numpy()).length == pytest.approx(106.0)
    # The border at the antimeridian is kept at 180 only.
    west = shapely.intersection(
        shapely.union_all(boundaries.geometry.to_numpy()),
        shapely.LineString([(-180, -90), (-180, 90)]),
    )
    assert west.length == pytest.approx(5.0)
    # Contiguous edges are one line: the region at -180 is one closed ring.
    assert np.isclose(lengths, 20.0).sum() == 1


def test_write_main_centerlines_keeps_the_main_lines(tmp_path: Path) -> None:
    lines = gpd.GeoDataFrame(
        {"rgi_id": ["a", "a", "b"], "is_main": [True, False, True]},
        geometry=shapely.linestrings([[(0, 0), (1, 1)], [(0, 1), (1, 1)], [(2, 2), (3, 3)]]),
        crs="OGC:CRS84",
    )
    lines.to_parquet(tmp_path / "c.parquet")
    main = gpd.read_parquet(
        tiles.write_main_centerlines(tmp_path / "c.parquet", tmp_path / "m.parquet")
    )
    assert main["is_main"].all()
    assert list(main["rgi_id"]) == ["a", "b"]


def test_version_layers_cover_every_product(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{name}.parquet" for name in tiles.ARCHIVE_PRODUCTS}
    zooms = range(tiles.GLACIERS_COMPLETE_ZOOM)
    overviews = {
        name: {z: tmp_path / f"{name}-z{z}.parquet" for z in zooms}
        for name in tiles.OVERVIEW_COLUMNS
    }
    layers = tiles.version_layers(
        paths,
        tmp_path / "labels.parquet",
        tmp_path / "rl.parquet",
        tmp_path / "rb.parquet",
        tmp_path / "main.parquet",
        overviews,
    )
    assert {layer.name for layer in layers} == {
        "regions",
        "region-boundaries",
        "region-labels",
        "complexes",
        "glaciers",
        "glacier-labels",
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
    }
    # The main centerlines come first. The other centerlines enter with the
    # divides.
    first = {
        name: min(b.minzoom for b in layers if b.name == name)
        for name in ("centerlines", "intersects")
    }
    assert first["intersects"] == first["centerlines"] + 1
    main_band = [b for b in layers if b.source == tmp_path / "main.parquet"]
    assert [(b.minzoom, b.maxzoom) for b in main_band] == [(first["centerlines"],) * 2]
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
