"""The ``tiles`` step: build the web-map archive from the staged GeoParquet files."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pmtiles.tile import Compression, deserialize_header, serialize_header
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.affinity import translate

from rgi_catalog.paths import CACHE, STAGING, version_dir
from rgi_catalog.pipeline import output_path
from rgi_catalog.sources import SourcePin, fetch

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

TYLERTOO = SourcePin(
    key="tylertoo",
    url=(
        "https://github.com/geoparquet-io/tylertoo/releases/download/v0.8.0/"
        "tylertoo-0.8.0-x86_64-unknown-linux-musl.tar.gz"
    ),
    sha256="d294ec4b1447d33d0201d316035daaf09bf1ba8eeccf5e5eb8a2cbfc592a41a7",
    size=12_780_986,
    filename="tylertoo-0.8.0-x86_64-unknown-linux-musl.tar.gz",
)
TYLERTOO_MEMBER = "tylertoo-0.8.0-x86_64-unknown-linux-musl/tylertoo"

ARCHIVE_NAME = "Randolph Glacier Inventory 7.0 Mirror"
ARCHIVE_ATTRIBUTION = "RGI 7.0 Consortium (2023)"
ARCHIVE_DESCRIPTION = (
    "Glacier outlines and names from the Randolph Glacier Inventory 7.0. "
    "Unofficial mirror, not endorsed by the RGI Consortium."
)

# Every layer stops at this zoom, because a client overzooms one source as a
# whole. A z12 tile resolves about 2.4 m at the equator, finer than the
# imagery the outlines were drawn from.
MAXZOOM = 12
GLACIERS_MINZOOM = 0
# From this zoom on, the glaciers layer holds every glacier.
GLACIERS_COMPLETE_ZOOM = 10
# Below GLACIERS_COMPLETE_ZOOM a glacier is a simplified outline from the zoom
# at which it spans this many pixels. Before that it is a point.
SHAPE_MIN_PX = 3
# The circumference of the Web Mercator world, in metres.
WORLD_M = 2 * math.pi * 6378137
# MapLibre draws a vector tile 512 pixels wide.
TILE_PX = 512
LABEL_MINZOOM = 7
# A glacier of this area gets its label at GLACIERS_COMPLETE_ZOOM + 1.
LABEL_REFERENCE_KM2 = 1.0

# Arrow types a vector tile cannot store as a property.
_NESTED = (pa.types.is_list, pa.types.is_large_list, pa.types.is_struct, pa.types.is_map)


class TileDropError(Exception):
    """The tiler dropped features in a band that must keep all of them."""


@dataclass(frozen=True)
class LayerSpec:
    """One zoom band of one vector layer.

    Several specs with the same ``name`` and disjoint zoom ranges build one
    layer with different settings per band.
    """

    name: str
    source: Path
    minzoom: int
    maxzoom: int
    extra_args: tuple[str, ...] = ()
    # The band must keep every feature. The build fails if the tiler drops one.
    complete: bool = False
    # The column of a feature's entry zoom (``--entry-zoom``). A complete band
    # must keep a feature from that zoom on.
    entry_zoom_column: str | None = None
    # The properties the band carries, of those the source has. None carries
    # every scalar column (:func:`tile_properties`).
    properties: tuple[str, ...] | None = None
    # Tile this many zooms past ``maxzoom`` and keep only ``minzoom`` to
    # ``maxzoom``. The finest zoom of a tiling keeps every source feature, so
    # a padded band thins its own last zoom like the others.
    pad_zoom: int = 0


def tylertoo_binary(cache_dir: Path = CACHE) -> Path:
    """Return the pinned tylertoo executable, downloading it if needed.

    The PyPI wheel has only the Python API, which cannot build a multi-layer
    archive. The release binary has the full command line.

    Parameters
    ----------
    cache_dir
        The directory that holds verified downloads.

    Returns
    -------
    Path
        The executable.
    """
    exe = cache_dir / "bin" / "tylertoo-0.8.0"
    if exe.exists():
        return exe
    archive = fetch(TYLERTOO, cache_dir)
    exe.parent.mkdir(parents=True, exist_ok=True)
    part = exe.with_suffix(".part")
    with tarfile.open(archive) as tar:
        member = tar.extractfile(TYLERTOO_MEMBER)
        if member is None:
            msg = f"{archive.name} has no {TYLERTOO_MEMBER}"
            raise FileNotFoundError(msg)
        with member, part.open("wb") as out:
            shutil.copyfileobj(member, out)
    part.chmod(0o755)
    part.rename(exe)
    return exe


def _run(*args: str | Path) -> None:
    """Run tylertoo and raise with its output if it fails."""
    cmd = [str(tylertoo_binary()), *(str(a) for a in args)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        msg = f"{' '.join(cmd)} failed:\n{done.stderr[-4000:]}"
        raise RuntimeError(msg)


def label_minzoom(area_km2: float) -> int:
    """Return the first zoom at which a glacier's name is drawn.

    Each zoom step quadruples a glacier's area on screen, so the entry zoom
    falls by one for every factor of 4 in area. A glacier of 1 km² gets its
    label at z11.

    Parameters
    ----------
    area_km2
        The glacier's area.

    Returns
    -------
    int
        A zoom from :data:`LABEL_MINZOOM` to :data:`MAXZOOM`.
    """
    if area_km2 <= 0:
        return MAXZOOM
    zoom = GLACIERS_COMPLETE_ZOOM + 1 - math.floor(math.log2(area_km2 / LABEL_REFERENCE_KM2) / 2)
    return min(MAXZOOM, max(LABEL_MINZOOM, zoom))


def tile_properties(parquet: Path) -> list[str]:
    """Return the columns of a file that a vector tile can store.

    List, struct and map columns (the hypsometry, the RGI 6 links,
    ``glacier_ids``, ``bbox``) and the geometry are left out.

    Parameters
    ----------
    parquet
        A GeoParquet file.

    Returns
    -------
    list[str]
        The scalar columns, in file order.
    """
    schema = pq.read_schema(parquet)
    geo = json.loads((schema.metadata or {}).get(b"geo", b"{}"))
    geometry = geo.get("primary_column", "geometry")
    return [
        field.name
        for field in schema
        if field.name != geometry and not any(is_nested(field.type) for is_nested in _NESTED)
    ]


def pixel_m(zoom: int) -> float:
    """Return the size of a screen pixel at the equator, in Web Mercator metres.

    Parameters
    ----------
    zoom
        The zoom.

    Returns
    -------
    float
        The pixel size of a :data:`TILE_PX` tile.
    """
    return WORLD_M / (TILE_PX * 2**zoom)


def shape_minzoom(extent_m: np.ndarray) -> np.ndarray:
    """Return the zoom from which each feature is drawn as an outline.

    Parameters
    ----------
    extent_m
        The longer side of each feature's Web Mercator bounding box, in metres.

    Returns
    -------
    np.ndarray
        The first zoom at which the feature spans :data:`SHAPE_MIN_PX`
        pixels, at most :data:`GLACIERS_COMPLETE_ZOOM`.
    """
    zooms = np.full(len(extent_m), GLACIERS_COMPLETE_ZOOM, dtype=np.int64)
    for zoom in range(GLACIERS_COMPLETE_ZOOM - 1, -1, -1):
        zooms[extent_m >= SHAPE_MIN_PX * pixel_m(zoom)] = zoom
    return zooms


def write_overview(source: Path, out_dir: Path, columns: Sequence[str]) -> dict[int, Path]:
    """Write the input of each overview zoom of a polygon layer.

    Below :data:`GLACIERS_COMPLETE_ZOOM` a feature that spans
    :data:`SHAPE_MIN_PX` pixels is its outline, and a smaller one is RGI's
    point (``cenlon``, ``cenlat``). Large glaciers then keep their shape at
    low zooms, and a small one is a dot.

    Parameters
    ----------
    source
        The GeoParquet file of the layer.
    out_dir
        The directory to write into.
    columns
        The columns the overview carries, of those the source can tile.

    Returns
    -------
    dict[int, Path]
        The GeoParquet file of each zoom from :data:`GLACIERS_MINZOOM`.
    """
    keep = [c for c in columns if c in tile_properties(source)]
    frame = gpd.read_parquet(source, columns=[*keep, "cenlon", "cenlat", "geometry"])
    bounds = frame.geometry.to_crs(3857).bounds
    extent = np.maximum(bounds["maxx"] - bounds["minx"], bounds["maxy"] - bounds["miny"])
    shape_zoom = shape_minzoom(extent.to_numpy())
    points = gpd.points_from_xy(frame["cenlon"], frame["cenlat"], crs=frame.crs)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for zoom in range(GLACIERS_MINZOOM, GLACIERS_COMPLETE_ZOOM):
        geometry = np.where(shape_zoom <= zoom, frame.geometry.to_numpy(), points)
        layer = gpd.GeoDataFrame(frame[keep], geometry=list(geometry), crs=frame.crs)
        out[zoom] = out_dir / f"z{zoom}.parquet"
        layer.to_parquet(out[zoom], index=False)
    return out


def write_labels(glaciers_parquet: Path, out: Path) -> Path:
    """Write the label points: one per named glacier, at RGI's own point.

    Parameters
    ----------
    glaciers_parquet
        The glaciers GeoParquet file.
    out
        The label GeoParquet file to write.

    Returns
    -------
    Path
        ``out``.
    """
    table = pq.read_table(
        glaciers_parquet,
        columns=["rgi_id", "display_name", "area_km2", "cenlon", "cenlat"],
    ).to_pandas()
    named = table.loc[table["display_name"].notna()]
    labels = gpd.GeoDataFrame(
        {
            "rgi_id": named["rgi_id"].to_numpy(),
            "display_name": named["display_name"].to_numpy(),
            "area_km2": named["area_km2"].to_numpy(),
            "label_minzoom": [label_minzoom(a) for a in named["area_km2"]],
        },
        geometry=gpd.points_from_xy(named["cenlon"], named["cenlat"]),
        crs="EPSG:4326",
    ).astype({"label_minzoom": "uint8"})
    out.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(out, index=False)
    return out


# The overview zooms below GLACIERS_COMPLETE_ZOOM (write_overview). Every
# outline is kept. The points are thinned to one per grid cell of 4 GSD, about
# a pixel, and the largest feature wins each cell. Without the density budget
# every cell keeps one.
POLYGON_OVERVIEW = (
    "--no-density-drop",
    "--polygon-thinning",
    "0",
    "--polygon-visibility",
    "0",
    "--sort-key",
    "area_km2",
)
# The overview carries only the key and what the styles read. Each point
# stands for a grid cell, and every column would make the z0 tile 314 KB.
GLACIER_OVERVIEW_COLUMNS = (
    "rgi_id",
    "display_name",
    "area_km2",
    "zmed_m",
    "surge_type",
    "term_type",
    "is_rgi6",
)
COMPLEX_OVERVIEW_COLUMNS = ("rgi_id", "area_km2")
# The overview columns by layer, for the documentation.
OVERVIEW_COLUMNS = {"glaciers": GLACIER_OVERVIEW_COLUMNS, "complexes": COMPLEX_OVERVIEW_COLUMNS}
# Polygons from GLACIERS_COMPLETE_ZOOM on. Density drop, cell thinning and the
# visibility gate each drop glaciers. Simplification at the default 1 GSD
# collapses two slivers of 0.01 km² at z10. Half a GSD keeps them.
POLYGON_COMPLETE = (
    "--no-density-drop",
    "--polygon-thinning",
    "0",
    "--polygon-visibility",
    "0",
    "--simplify-factor",
    "0.5",
)
# Lines that must all be kept. Line coalescing joins touching segments into
# one feature with one set of attributes, so it is off.
LINE_COMPLETE = (
    "--no-density-drop",
    "--line-thinning",
    "0",
    "--line-visibility",
    "0",
    "--no-coalesce-lines",
)
CENTERLINES_MINZOOM = 8
# Intersects are divides between glaciers, readable only at high zooms.
INTERSECTS_MINZOOM = 10
# Neighbouring regions split a shared border at different vertices. On this
# grid the outlines node into one set of lines. A degree of 1e-5 is about
# 1.1 m, finer than the 2.4 m that a z12 tile resolves.
BOUNDARY_GRID = 1e-5
# The products the archive draws, by collection name.
ARCHIVE_PRODUCTS = ("regions", "complexes", "glaciers", "centerlines", "intersects")


def overview_layers(name: str, overview: dict[int, Path]) -> list[LayerSpec]:
    """Return one band per overview zoom of a polygon layer.

    Parameters
    ----------
    name
        The layer name.
    overview
        The input of each zoom, from :func:`write_overview`.

    Returns
    -------
    list[LayerSpec]
        One band per zoom, padded by a zoom so that its points are thinned.
    """
    return [
        LayerSpec(name, path, zoom, zoom, POLYGON_OVERVIEW, pad_zoom=1)
        for zoom, path in sorted(overview.items())
    ]


def glacier_layers(glaciers: Path, labels: Path, overview: dict[int, Path]) -> list[LayerSpec]:
    """Return the bands of the ``glaciers`` and ``glacier-labels`` layers.

    Parameters
    ----------
    glaciers
        The glaciers GeoParquet file.
    labels
        The label file from :func:`write_labels`.
    overview
        The overview input of each zoom, from :func:`write_overview`.

    Returns
    -------
    list[LayerSpec]
        Below :data:`GLACIERS_COMPLETE_ZOOM` the overview: outlines of the
        glaciers that span :data:`SHAPE_MIN_PX` pixels, and a point per grid
        cell for the others. From it on every glacier is kept. Each label
        enters at its ``label_minzoom`` and is never thinned.
    """
    entry = ",".join(f"{z}={z}" for z in range(LABEL_MINZOOM, MAXZOOM + 1))
    return [
        *overview_layers("glaciers", overview),
        LayerSpec(
            "glaciers",
            glaciers,
            GLACIERS_COMPLETE_ZOOM,
            MAXZOOM,
            POLYGON_COMPLETE,
            complete=True,
        ),
        LayerSpec(
            "glacier-labels",
            labels,
            LABEL_MINZOOM,
            MAXZOOM,
            ("--entry-zoom", f"label_minzoom:{entry}", "--no-density-drop"),
            complete=True,
            entry_zoom_column="label_minzoom",
        ),
    ]


def write_region_labels(regions_parquet: Path, out: Path) -> Path:
    """Write one label point per region, inside its largest polygon.

    The regions file has no label point, so the point is derived: the
    ``point_on_surface`` of the region's largest polygon. Region 10 and
    region 19-15 are MultiPolygons, split at the antimeridian.

    Parameters
    ----------
    regions_parquet
        The regions GeoParquet file.
    out
        The label GeoParquet file to write.

    Returns
    -------
    Path
        ``out``.
    """
    regions = gpd.read_parquet(regions_parquet).explode(index_parts=False)
    regions = regions.reset_index(drop=True)
    # Square degrees, enough to choose between the parts of one region.
    areas = pd.Series(shapely.area(regions.geometry.to_numpy()), index=regions.index)
    largest = regions.loc[areas.groupby([regions["level"], regions["long_code"]]).idxmax()]
    labels = gpd.GeoDataFrame(
        largest[["level", "o1region", "o2region", "full_name"]].reset_index(drop=True),
        geometry=shapely.point_on_surface(largest.geometry.to_numpy()),
        crs=regions.crs,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(out, index=False)
    return out


def _lines(geometry: Any) -> shapely.MultiLineString:
    """Return the line parts of an overlay result, without its points."""
    parts = shapely.get_parts(shapely.get_parts(geometry))
    return shapely.multilinestrings(parts[shapely.get_type_id(parts) == 1])


def _meridian(x: float) -> shapely.LineString:
    return shapely.LineString([(x, -90), (x, 90)])


def _antimeridian_cut(region: Any) -> shapely.MultiLineString:
    """Return the outline a region has at both 180 and -180, on both sides.

    That outline closes the region where it is split at the antimeridian. It
    is not a border.
    """
    outline = shapely.boundary(region)
    east = _lines(shapely.intersection(outline, _meridian(180), grid_size=BOUNDARY_GRID))
    west = _lines(shapely.intersection(outline, _meridian(-180), grid_size=BOUNDARY_GRID))
    cut = _lines(shapely.intersection(east, translate(west, 360), grid_size=BOUNDARY_GRID))
    return _lines(shapely.union(cut, translate(cut, -360), grid_size=BOUNDARY_GRID))


def write_region_boundaries(regions_parquet: Path, out: Path) -> Path:
    """Write each region border once, as lines with the lowest level it bounds.

    Neighbouring polygons store a shared border once each, in opposite
    directions, and a dash pattern drawn twice looks solid. The outlines of
    each level are snapped to :data:`BOUNDARY_GRID` and noded into one set of
    lines. A second-order border on a first-order border is level 1. The
    outline that closes a region at the antimeridian is left out. A border at
    the antimeridian is kept at 180 only. Contiguous lines of one level are
    merged, so a dash pattern runs along them.

    Parameters
    ----------
    regions_parquet
        The regions GeoParquet file.
    out
        The boundary GeoParquet file to write, one row per merged line.

    Returns
    -------
    Path
        ``out``.
    """
    regions = gpd.read_parquet(regions_parquet)
    levels = sorted(regions["level"].unique())
    lines: dict[Any, Any] = {}
    for level in levels:
        polygons = regions.geometry[regions["level"] == level].to_numpy()
        outlines = shapely.union_all(shapely.boundary(polygons), grid_size=BOUNDARY_GRID)
        cuts = shapely.union_all([_antimeridian_cut(p) for p in polygons])
        lines[level] = _lines(shapely.difference(outlines, cuts, grid_size=BOUNDARY_GRID))
    east = _lines(
        shapely.intersection(
            shapely.union_all(list(lines.values()), grid_size=BOUNDARY_GRID),
            _meridian(180),
            grid_size=BOUNDARY_GRID,
        )
    )
    for level, line in lines.items():
        west = _lines(shapely.intersection(line, _meridian(-180), grid_size=BOUNDARY_GRID))
        twin = _lines(shapely.intersection(translate(west, 360), east, grid_size=BOUNDARY_GRID))
        kept = shapely.difference(line, translate(twin, -360), grid_size=BOUNDARY_GRID)
        lines[level] = _lines(shapely.union(kept, twin, grid_size=BOUNDARY_GRID))
    # Each level gives up the lines of the levels above it.
    for i, level in enumerate(levels):
        for lower in levels[:i]:
            lines[level] = _lines(
                shapely.difference(lines[level], lines[lower], grid_size=BOUNDARY_GRID)
            )
    boundaries = gpd.GeoDataFrame(
        {"level": np.array(levels, dtype=regions["level"].dtype)},
        geometry=[shapely.line_merge(lines[level]) for level in levels],
        crs=regions.crs,
    )
    boundaries = boundaries.explode(index_parts=False).reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    boundaries.to_parquet(out, index=False)
    return out


def version_layers(
    products: dict[str, Path],
    labels: Path,
    region_labels: Path,
    region_boundaries: Path,
    overviews: dict[str, dict[int, Path]],
) -> list[LayerSpec]:
    """Return the bands of every layer of the archive, bottom to top.

    Parameters
    ----------
    products
        The GeoParquet file of each name in :data:`ARCHIVE_PRODUCTS`.
    labels
        The glacier label file from :func:`write_labels`.
    region_labels
        The region label file from :func:`write_region_labels`.
    region_boundaries
        The region boundary file from :func:`write_region_boundaries`.
    overviews
        The overview inputs of the glaciers and the complexes, by layer name,
        from :func:`write_overview`.

    Returns
    -------
    list[LayerSpec]
        The regions, their boundaries and their labels at every zoom. The complexes and the
        glaciers as in :func:`glacier_layers`. The centerlines from
        :data:`CENTERLINES_MINZOOM`, all of them from
        :data:`GLACIERS_COMPLETE_ZOOM`. The intersects from
        :data:`INTERSECTS_MINZOOM`, all of them.
    """
    lines = (*LINE_COMPLETE, "--simplify-factor", "0.5")
    return [
        LayerSpec(
            "regions",
            products["regions"],
            0,
            MAXZOOM,
            ("--no-density-drop", "--polygon-thinning", "0", "--polygon-visibility", "0"),
            complete=True,
        ),
        # Simplification collapses short boundary lines at low zooms.
        LayerSpec(
            "region-boundaries",
            region_boundaries,
            0,
            MAXZOOM,
            (*LINE_COMPLETE, "--simplify-factor", "0"),
            complete=True,
        ),
        LayerSpec(
            "region-labels",
            region_labels,
            0,
            MAXZOOM,
            ("--no-density-drop", "--point-thinning", "0"),
            complete=True,
        ),
        *overview_layers("complexes", overviews["complexes"]),
        LayerSpec(
            "complexes",
            products["complexes"],
            GLACIERS_COMPLETE_ZOOM,
            MAXZOOM,
            POLYGON_COMPLETE,
            complete=True,
        ),
        *glacier_layers(products["glaciers"], labels, overviews["glaciers"]),
        LayerSpec(
            "centerlines",
            products["centerlines"],
            CENTERLINES_MINZOOM,
            GLACIERS_COMPLETE_ZOOM - 1,
            lines,
        ),
        LayerSpec(
            "centerlines",
            products["centerlines"],
            GLACIERS_COMPLETE_ZOOM,
            MAXZOOM,
            lines,
            complete=True,
        ),
        # Simplification at half a GSD still collapses short divides.
        LayerSpec(
            "intersects",
            products["intersects"],
            INTERSECTS_MINZOOM,
            MAXZOOM,
            (*LINE_COMPLETE, "--simplify-factor", "0"),
            complete=True,
        ),
    ]


def build_archive(
    layers: Sequence[LayerSpec],
    out: Path,
    *,
    name: str,
    attribution: str,
    description: str,
) -> Path:
    """Build one PMTiles archive with one vector layer per layer name.

    Each band is tiled on its own, then ``tylertoo pyramid`` joins the bands.
    Bands of different layers may share zooms.

    Parameters
    ----------
    layers
        The bands.
    out
        The archive to write. It is replaced only once the new one is complete.
    name, attribution, description
        The archive's metadata.

    Returns
    -------
    Path
        ``out``.

    Raises
    ------
    TileDropError
        If a band marked ``complete`` dropped a feature.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=f".{out.stem}-") as tmp:
        work = Path(tmp)
        bands: list[str] = []
        for i, layer in enumerate(layers):
            band = work / f"band-{i}.pmtiles"
            report = work / f"band-{i}.json"
            available = tile_properties(layer.source)
            if layer.properties is not None:
                available = [p for p in available if p in layer.properties]
            props = [a for p in available for a in ("--include-property", p)]
            _run(
                "tiles",
                layer.source,
                band,
                "--layer-name",
                layer.name,
                "--min-zoom",
                str(layer.minzoom),
                "--max-zoom",
                str(layer.maxzoom + layer.pad_zoom),
                "--no-simple-clip-fastpath",
                "--report",
                report,
                *props,
                *layer.extra_args,
            )
            if layer.complete:
                _check_complete(layer, json.loads(report.read_text())["export"])
            bands.extend(["--band", f"{layer.minzoom}-{layer.maxzoom}:{band}:{layer.name}"])
        joined = work / "archive.pmtiles"
        _run("pyramid", "--work-dir", work, *bands, joined)
        # The bands are as large as the archive. Free the disk before the
        # metadata pass writes its copy.
        for band in work.glob("band-*.pmtiles"):
            band.unlink()
        set_metadata(
            joined, {"name": name, "attribution": attribution, "description": description}
        )
        joined.replace(out)
    return out


def _check_complete(layer: LayerSpec, export: dict[str, Any]) -> None:
    """Refuse a band that lost a feature it must keep, at any zoom."""
    where = f"layer {layer.name} z{layer.minzoom}-{layer.maxzoom}"
    dropped = export["oversized_tiles"], export["encode_dropped_features"]
    if any(dropped):
        msg = f"{where}: {dropped[0]} oversized tiles and {dropped[1]} features dropped"
        raise TileDropError(msg)
    if layer.entry_zoom_column is None:
        n = pq.ParquetFile(layer.source).metadata.num_rows
        expected = dict.fromkeys(range(layer.minzoom, layer.maxzoom + 1), n)
    else:
        entry = pq.read_table(layer.source, columns=[layer.entry_zoom_column]).column(0)
        zooms = entry.to_numpy()
        expected = {z: int((zooms <= z).sum()) for z in range(layer.minzoom, layer.maxzoom + 1)}
    kept = {z["zoom"]: z["level_feature_count"] for z in export["zooms"]}
    for zoom, n in expected.items():
        if kept.get(zoom, 0) != n:
            msg = f"{where}: z{zoom} keeps {kept.get(zoom, 0)} of {n} features"
            raise TileDropError(msg)


def set_metadata(archive: Path, updates: dict[str, str]) -> None:
    """Merge keys into a PMTiles archive's metadata and leave the tiles as they are.

    The header, directories and tile data are copied byte for byte. Only the
    metadata block and the offsets that follow it change.

    Parameters
    ----------
    archive
        The archive, rewritten in place.
    updates
        The metadata keys to set.
    """
    with archive.open("rb") as src:
        header = deserialize_header(src.read(127))
        sections: dict[str, bytes] = {}
        for key, offset, length in (
            ("root", header["root_offset"], header["root_length"]),
            ("metadata", header["metadata_offset"], header["metadata_length"]),
            ("leaf_directory", header["leaf_directory_offset"], header["leaf_directory_length"]),
        ):
            src.seek(offset)
            sections[key] = src.read(length)
        meta_bytes = sections["metadata"]
        gzipped = header["internal_compression"] == Compression.GZIP
        meta = json.loads(gzip.decompress(meta_bytes) if gzipped else meta_bytes)
        meta.update(updates)
        new_meta = json.dumps(meta, sort_keys=True, ensure_ascii=False).encode()
        if gzipped:
            new_meta = gzip.compress(new_meta, mtime=0)
        header["root_offset"] = 127
        header["metadata_offset"] = 127 + len(sections["root"])
        header["metadata_length"] = len(new_meta)
        header["leaf_directory_offset"] = header["metadata_offset"] + len(new_meta)
        tile_data_offset = header["tile_data_offset"]
        header["tile_data_offset"] = header["leaf_directory_offset"] + len(
            sections["leaf_directory"]
        )
        tmp = archive.with_suffix(".tmp")
        with tmp.open("wb") as dst:
            dst.write(serialize_header(header))
            dst.write(sections["root"])
            dst.write(new_meta)
            dst.write(sections["leaf_directory"])
            src.seek(tile_data_offset)
            _copy_exact(src, dst, header["tile_data_length"])
    tmp.replace(archive)


def _copy_exact(src: Any, dst: Any, length: int) -> None:
    while length:
        chunk = src.read(min(length, 1 << 20))
        if not chunk:
            msg = "archive ends inside its tile data"
            raise EOFError(msg)
        dst.write(chunk)
        length -= len(chunk)


def decode(archive: Path, out: Path, *, layer: str | None = None) -> Path:
    """Decode an archive's tiles to GeoParquet, one row per feature per tile.

    Parameters
    ----------
    archive
        The PMTiles archive.
    out
        The GeoParquet file to write.
    layer
        Decode only this layer.

    Returns
    -------
    Path
        ``out``.
    """
    _run("decode", "--force", archive, out, *(("--layer", layer) if layer else ()))
    return out


def archive_path(staging: Path, version: str) -> Path:
    """Return the staged archive. Every collection of the version draws from it.

    Parameters
    ----------
    staging
        The staging root.
    version
        The RGI version.

    Returns
    -------
    Path
        ``staging/v{version}/rgi{version}.pmtiles``.
    """
    return staging / version_dir(version) / f"rgi{version}.pmtiles"


def build_tiles(version: str, *, staging: Path = STAGING) -> Path:
    """Build the web-map archive of a version from its staged files.

    Parameters
    ----------
    version
        The RGI version.
    staging
        The staging root.

    Returns
    -------
    Path
        The archive.
    """
    products = {name: output_path(staging, version, name) for name in ARCHIVE_PRODUCTS}
    work = staging / version_dir(version) / ".tiles"
    labels = write_labels(products["glaciers"], work / "labels.parquet")
    region_labels = write_region_labels(products["regions"], work / "region-labels.parquet")
    region_boundaries = write_region_boundaries(
        products["regions"], work / "region-boundaries.parquet"
    )
    # The overview inputs hold most outlines once per zoom. They go once the
    # archive is built.
    with tempfile.TemporaryDirectory(dir=work, prefix="overview-") as tmp:
        overviews = {
            name: write_overview(products[name], Path(tmp) / name, columns)
            for name, columns in OVERVIEW_COLUMNS.items()
        }
        return build_archive(
            version_layers(products, labels, region_labels, region_boundaries, overviews),
            archive_path(staging, version),
            name=ARCHIVE_NAME,
            attribution=ARCHIVE_ATTRIBUTION,
            description=ARCHIVE_DESCRIPTION,
        )


def _tiles(args: argparse.Namespace) -> None:
    out = build_tiles(args.version)
    print(f"ok  {out}: {out.stat().st_size / 1e6:.1f} MB")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``tiles`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("tiles", help="build the web-map archive")
    parser.add_argument("--version", required=True)
    parser.set_defaults(func=_tiles)
