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

from rgi_catalog.glyphs import GLYPH_PX, LABEL_LETTER_SPACING, LABEL_TEXT_SIZE, load_advances
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
# A line wider than this in longitude crosses the antimeridian.
HALF_WORLD_DEG = 180
# The latitude at which the Web Mercator world ends.
MERCATOR_MAX_LAT = math.degrees(math.atan(math.sinh(math.pi)))
# MapLibre draws a vector tile 512 pixels wide.
TILE_PX = 512
# The coordinate units across a vector tile.
TILE_EXTENT = 4096
LABEL_MINZOOM = 7
# A glacier of this area gets its label at GLACIERS_COMPLETE_ZOOM + 1.
LABEL_REFERENCE_KM2 = 1.0
# A name follows its centerline once the line is long enough. The fit
# assumes a line-center label in glyphs.FONT at glyphs.LABEL_TEXT_SIZE.
# The standard deviation of the smoothing, in pixels at the line's zoom.
LABEL_SMOOTH_PX = 4.0
# The line is a stretch of the centerline, this many padded names long but
# at most TILE_PX, unless the name needs more. The label tiles have a buffer
# of TILE_PX, so each tile then holds the whole line at its line_zoom.
LABEL_STRETCH = 1.5
# The stretch slides up the centerline from the terminus in steps of this
# many pixels. The downstream end of the name keeps this part of the
# centerline's length to the terminus, and at least LABEL_PAD_PX. The
# middle of the centerline is always a candidate.
LABEL_SLIDE_PX = 2.0
LABEL_TONGUE_MARGIN = 0.1
# MapLibre's text-max-angle rule: the corners in a window of 3/5 of the text
# size may turn by at most 45° (the default) in total. The tiler moves each
# vertex by up to 1/16 pixel, which changes a short segment's turn by about
# 2°. The check keeps 5° of the 45° in reserve.
LABEL_WINDOW_PX = 3 / 5 * LABEL_TEXT_SIZE
LABEL_MAX_ANGLE = math.radians(45 - 5)
# The free line kept on each side of a name, one angle window.
LABEL_PAD_PX = LABEL_WINDOW_PX

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


def mercator_extent(geometry: gpd.GeoSeries) -> np.ndarray:
    """Return the longer side of each feature's Web Mercator bounding box.

    Parameters
    ----------
    geometry
        The features.

    Returns
    -------
    np.ndarray
        The extents, in metres.
    """
    bounds = shapely.bounds(geometry.to_crs(3857).to_numpy())
    return np.maximum(bounds[:, 2] - bounds[:, 0], bounds[:, 3] - bounds[:, 1])


def span_minzoom(
    extent_m: np.ndarray, min_px: float, minzoom: int, maxzoom: int | np.ndarray
) -> np.ndarray:
    """Return the first zoom at which each feature spans a number of pixels.

    Parameters
    ----------
    extent_m
        The longer side of each feature's Web Mercator bounding box, in metres.
    min_px
        The pixels the feature must span.
    minzoom
        The first zoom returned.
    maxzoom
        The zoom of a feature that spans fewer pixels before it, for all
        features or for each one.

    Returns
    -------
    np.ndarray
        A zoom from ``minzoom`` to ``maxzoom`` per feature.
    """
    maxzoom = np.broadcast_to(maxzoom, extent_m.shape)
    zooms = maxzoom.astype(np.int64)
    for zoom in range(int(maxzoom.max(initial=minzoom)) - 1, minzoom - 1, -1):
        zooms[(extent_m >= min_px * pixel_m(zoom)) & (zoom < maxzoom)] = zoom
    return zooms


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
    return span_minzoom(extent_m, SHAPE_MIN_PX, GLACIERS_MINZOOM, GLACIERS_COMPLETE_ZOOM)


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
    shape_zoom = shape_minzoom(mercator_extent(frame.geometry))
    points = gpd.points_from_xy(frame["cenlon"], frame["cenlat"], crs=frame.crs)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for zoom in range(GLACIERS_MINZOOM, GLACIERS_COMPLETE_ZOOM):
        geometry = np.where(shape_zoom <= zoom, frame.geometry.to_numpy(), points)
        layer = gpd.GeoDataFrame(frame[keep], geometry=list(geometry), crs=frame.crs)
        out[zoom] = out_dir / f"z{zoom}.parquet"
        layer.to_parquet(out[zoom], index=False)
    return out


def label_width_px(name: str) -> float:
    """Return the width of a glacier name on the map, in pixels, as MapLibre shapes it.

    Each glyph advances by its advance in the font, scaled from
    :data:`glyphs.GLYPH_PX` to :data:`LABEL_TEXT_SIZE`. The letter spacing
    falls between the glyphs. MapLibre leaves out a glyph the font does
    not have.

    Parameters
    ----------
    name
        The name.

    Returns
    -------
    float
        The width of the shaped name.
    """
    advances = load_advances()
    shaped = [advances[ord(c)] for c in name if ord(c) in advances]
    if not shaped:
        return 0.0
    scale = LABEL_TEXT_SIZE / GLYPH_PX
    spacing = LABEL_LETTER_SPACING * LABEL_TEXT_SIZE
    return sum(shaped) * scale + spacing * (len(shaped) - 1)


def _arc_length(coords: np.ndarray) -> np.ndarray:
    """Return the distance along a line at each vertex."""
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))])


def smooth_line(coords: np.ndarray, sigma: float) -> np.ndarray:
    """Return a line resampled at unit spacing and smoothed with a Gaussian.

    Parameters
    ----------
    coords
        The vertices, in pixels.
    sigma
        The standard deviation of the Gaussian, in pixels.

    Returns
    -------
    np.ndarray
        The smoothed vertices, one per pixel. The line is mirrored through
        each end vertex before the smoothing, so it keeps its ends.
    """
    distance = _arc_length(coords)
    steps = np.linspace(0, distance[-1], max(int(distance[-1]), 2) + 1)
    radius = math.ceil(3 * sigma)
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (offsets / sigma) ** 2)
    kernel /= kernel.sum()
    axes = []
    for axis in coords.T:
        resampled = np.interp(steps, distance, axis)
        padded = np.pad(resampled, radius, mode="reflect", reflect_type="odd")
        axes.append(np.convolve(padded, kernel, mode="valid"))
    return np.column_stack(axes)


def line_stretch(coords: np.ndarray, start: float, length: float) -> np.ndarray:
    """Return the part of a line of a given length from a given distance along it.

    Parameters
    ----------
    coords
        The vertices.
    start
        The distance along the line where the stretch starts.
    length
        The length to keep, in the units of ``coords``.

    Returns
    -------
    np.ndarray
        The vertices of the stretch.
    """
    distance = _arc_length(coords)
    end = start + length
    inner = coords[(distance > start) & (distance < end)]
    ends = [np.interp([d], distance, axis)[0] for d in (start, end) for axis in coords.T]
    return np.vstack([ends[:2], inner, ends[2:]])


def stretch_starts(line_px: float, label_px: float, keep_px: float) -> np.ndarray:
    """Return the starts of the stretches to try, from the terminus up.

    The centerline runs from the head to the terminus. The name sits at the
    middle of the stretch. Its downstream end keeps :data:`LABEL_TONGUE_MARGIN`
    of the line, at least :data:`LABEL_PAD_PX`, to the terminus. The margin
    is at most the one of a name at the middle of the line, so the middle
    stretch is always a candidate.

    Parameters
    ----------
    line_px
        The length of the centerline, in pixels.
    label_px
        The width of the name, in pixels.
    keep_px
        The length of the stretch, at most ``line_px``.

    Returns
    -------
    np.ndarray
        The distances from the head, in pixels, in descending order. The
        first start is the most downstream one.
    """
    margin = min(max(LABEL_PAD_PX, LABEL_TONGUE_MARGIN * line_px), (line_px - label_px) / 2)
    last = min(line_px - keep_px, line_px - margin - (keep_px + label_px) / 2)
    middle = (line_px - keep_px) / 2
    slide = np.arange(last, 0, -LABEL_SLIDE_PX)
    return np.unique(np.concatenate([slide, [middle, 0.0]]))[::-1]


def _turn(coords: np.ndarray, vertex: int) -> float:
    """Return the angle by which a line turns at an inner vertex, in radians."""
    before = coords[vertex] - coords[vertex - 1]
    after = coords[vertex + 1] - coords[vertex]
    delta = math.atan2(before[1], before[0]) - math.atan2(after[1], after[0])
    return abs((delta + math.pi) % (2 * math.pi) - math.pi)


def center_label_fits(coords: np.ndarray, label_px: float) -> bool:
    """Return whether MapLibre places a ``line-center`` label on a line.

    This ports MapLibre's ``getCenterAnchor`` and ``checkMaxAngle``. The
    label sits at the midpoint of the line. MapLibre drops it when the line
    ends under the label, or when the corners under the label turn by more
    than 45° within :data:`LABEL_WINDOW_PX`, 3/5 of the text size. The check
    uses :data:`LABEL_MAX_ANGLE`, which is stricter.

    Parameters
    ----------
    coords
        The vertices, in pixels, without repeated vertices.
    label_px
        The width of the label, in pixels.

    Returns
    -------
    bool
        True if MapLibre keeps the label.
    """
    distance = _arc_length(coords)
    center = distance[-1] / 2
    segment = int(np.searchsorted(distance, center, side="right")) - 1
    if segment >= len(coords) - 1:
        return False
    ratio = (center - distance[segment]) / (distance[segment + 1] - distance[segment])
    point = coords[segment] + ratio * (coords[segment + 1] - coords[segment])
    # Walk back to the first vertex under the label.
    index = segment + 1
    along = 0.0
    while along > -label_px / 2:
        index -= 1
        if index < 0:
            return False
        along -= float(np.hypot(*(coords[index] - point)))
        point = coords[index]
    along += distance[index + 1] - distance[index]
    index += 1
    # Sum the corners in a sliding window up to the end of the label.
    corners: list[tuple[float, float]] = []
    turned = 0.0
    while along < label_px / 2:
        if index + 1 >= len(coords):
            return False
        turn = _turn(coords, index)
        corners.append((along, turn))
        turned += turn
        while along - corners[0][0] > LABEL_WINDOW_PX:
            turned -= corners.pop(0)[1]
        if turned > LABEL_MAX_ANGLE:
            return False
        along += distance[index + 1] - distance[index]
        index += 1
    return True


def tile_grid(coords: np.ndarray) -> np.ndarray:
    """Return a line as a vector tile stores it, in pixels.

    A tile of :data:`TILE_PX` pixels has an extent of 4096 units, so a
    vertex moves to the nearest 1/8 pixel. A vertex that lands on the one
    before it is left out.

    Parameters
    ----------
    coords
        The vertices, in pixels.

    Returns
    -------
    np.ndarray
        The vertices on the tile grid.
    """
    units = TILE_EXTENT / TILE_PX
    grid = np.round(coords * units) / units
    moved = np.concatenate([[True], (np.diff(grid, axis=0) != 0).any(axis=1)])
    return grid[moved]


def label_line(coords_m: np.ndarray, name: str, minzoom: int) -> tuple[int, np.ndarray] | None:
    """Return the zoom and the line from which a name follows its centerline.

    At each zoom from ``minzoom`` to :data:`MAXZOOM` the line is smoothed by
    :data:`LABEL_SMOOTH_PX`. A stretch of :data:`LABEL_STRETCH` padded label
    widths, at most :data:`TILE_PX`, slides up the line from the terminus
    (:func:`stretch_starts`). The first stretch on the tile grid where
    MapLibre keeps the name with :data:`LABEL_PAD_PX` on each side
    (:func:`center_label_fits`) wins. The first zoom with such a stretch
    wins. The label band does not simplify, so the tile holds this line.

    Parameters
    ----------
    coords_m
        The vertices of the centerline, in Web Mercator metres.
    name
        The name.
    minzoom
        The first zoom at which the name is drawn.

    Returns
    -------
    tuple[int, np.ndarray] | None
        The zoom and the stretch in Web Mercator metres, or None if the name
        never fits.
    """
    label_px = label_width_px(name)
    needed_px = label_px + 2 * LABEL_PAD_PX
    length_m = _arc_length(coords_m)[-1]
    for zoom in range(minzoom, MAXZOOM + 1):
        if length_m / pixel_m(zoom) < needed_px:
            continue
        smoothed = smooth_line(coords_m / pixel_m(zoom), LABEL_SMOOTH_PX)
        smoothed_px = _arc_length(smoothed)[-1]
        if smoothed_px < needed_px:
            continue
        keep_px = min(smoothed_px, max(needed_px, min(LABEL_STRETCH * needed_px, TILE_PX)))
        for start in stretch_starts(smoothed_px, label_px, keep_px):
            stretch = line_stretch(smoothed, start, keep_px)
            stretch = np.asarray(shapely.simplify(shapely.LineString(stretch), 0.25).coords)
            stretch = tile_grid(stretch)
            if center_label_fits(stretch, needed_px):
                return zoom, stretch * pixel_m(zoom)
    return None


def main_centerlines(centerlines_parquet: Path, rgi_ids: Sequence[str]) -> gpd.GeoSeries:
    """Return the longest main centerline of each glacier, in Web Mercator.

    Parameters
    ----------
    centerlines_parquet
        The centerlines GeoParquet file.
    rgi_ids
        The glaciers.

    Returns
    -------
    gpd.GeoSeries
        One line per glacier that has one, indexed by the glacier's
        ``rgi_id``. A line beyond :data:`MERCATOR_MAX_LAT` or across the
        antimeridian is left out.
    """
    lines = gpd.read_parquet(
        centerlines_parquet,
        columns=["rgi_g_id", "is_main", "geometry"],
        filters=[("is_main", "==", True)],
    )
    lines = lines.loc[lines["rgi_g_id"].isin(rgi_ids)]
    bounds = shapely.bounds(lines.geometry.to_numpy())
    inside = (
        (bounds[:, 1] >= -MERCATOR_MAX_LAT)
        & (bounds[:, 3] <= MERCATOR_MAX_LAT)
        & (bounds[:, 2] - bounds[:, 0] < HALF_WORLD_DEG)
        & (shapely.get_type_id(lines.geometry.to_numpy()) == 1)
    )
    lines = lines.loc[inside].to_crs(3857)
    lines = lines.assign(length=lines.length).sort_values("length")
    lines = lines.drop_duplicates("rgi_g_id", keep="last")
    return lines.set_index("rgi_g_id").geometry


def write_labels(glaciers_parquet: Path, centerlines_parquet: Path, out: Path) -> Path:
    """Write the labels: a point per named glacier and a line for those that fit one.

    The point is RGI's own point. The line is a stretch of the glacier's
    main centerline near the terminus, smoothed (:func:`label_line`). Both carry ``line_zoom``,
    the zoom from which the line exists. It is null for a glacier without a
    line. ``label_minzoom`` is the zoom at which a feature enters: on a line
    it equals ``line_zoom``.

    Parameters
    ----------
    glaciers_parquet
        The glaciers GeoParquet file.
    centerlines_parquet
        The centerlines GeoParquet file.
    out
        The label GeoParquet file to write: the points, then the lines.

    Returns
    -------
    Path
        ``out``.
    """
    table = pq.read_table(
        glaciers_parquet,
        columns=["rgi_id", "display_name", "area_km2", "cenlon", "cenlat"],
    ).to_pandas()
    named = table.loc[table["display_name"].notna()].reset_index(drop=True)
    minzoom = [label_minzoom(a) for a in named["area_km2"]]
    centerlines = main_centerlines(centerlines_parquet, named["rgi_id"].tolist())
    line_zoom: list[int | None] = []
    lines: list[shapely.LineString] = []
    for rgi_id, name, zoom in zip(named["rgi_id"], named["display_name"], minzoom, strict=True):
        placed = None
        if rgi_id in centerlines.index:
            placed = label_line(np.asarray(centerlines[rgi_id].coords), name, zoom)
        line_zoom.append(None if placed is None else placed[0])
        if placed is not None:
            lines.append(shapely.LineString(placed[1]))
    points = gpd.GeoDataFrame(
        {
            "rgi_id": named["rgi_id"],
            "display_name": named["display_name"],
            "area_km2": named["area_km2"],
            "label_minzoom": minzoom,
            "line_zoom": pd.array(line_zoom, dtype="UInt8"),
        },
        geometry=gpd.points_from_xy(named["cenlon"], named["cenlat"]),
        crs="EPSG:4326",
    ).astype({"label_minzoom": "uint8"})
    with_line = points.loc[points["line_zoom"].notna()]
    line_features = gpd.GeoDataFrame(
        with_line.drop(columns="geometry").assign(
            label_minzoom=with_line["line_zoom"].astype("uint8")
        ),
        geometry=gpd.GeoSeries(lines, index=with_line.index, crs=3857).to_crs(4326),
    )
    labels = pd.concat([points, line_features], ignore_index=True)
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
# The main centerline of each glacier enters at CENTERLINES_MINZOOM at the
# latest. The other centerlines and the intersects, the divides between
# glaciers, enter a zoom later. At z8 they crowd the main lines.
CENTERLINES_MINZOOM = 8
INTERSECTS_MINZOOM = CENTERLINES_MINZOOM + 1
# A line enters earlier at the zoom at which it spans LINE_MIN_PX pixels, but
# not before LINES_MINZOOM. The long lines of an ice cap then show with its
# outline.
LINE_MIN_PX = 32
LINES_MINZOOM = 4
# Neighbouring regions split a shared border at different vertices. On this
# grid the outlines node into one set of lines. A degree of 1e-5 is about
# 1.1 m, finer than the 2.4 m that a z12 tile resolves.
BOUNDARY_GRID = 1e-5
# The products the archive draws, by collection name.
ARCHIVE_PRODUCTS = ("regions", "complexes", "glaciers", "centerlines", "intersects")


def entry_zoom_args(column: str, minzoom: int, maxzoom: int) -> tuple[str, str]:
    """Return the tiler arguments that make each feature enter at its own zoom.

    Parameters
    ----------
    column
        The column of each feature's entry zoom.
    minzoom, maxzoom
        The range of the entry zooms.

    Returns
    -------
    tuple[str, str]
        ``--entry-zoom`` and its value, which maps each zoom to itself.
    """
    zooms = ",".join(f"{z}={z}" for z in range(minzoom, maxzoom + 1))
    return "--entry-zoom", f"{column}:{zooms}"


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
            (
                *entry_zoom_args("label_minzoom", LABEL_MINZOOM, MAXZOOM),
                *LINE_COMPLETE,
                # The tiler's simplification merges the smoothed bends of a
                # label line into sharper corners, and MapLibre then drops
                # the label. label_line checks the line as written.
                "--simplify-factor",
                "0",
                # The tiler counts the buffer in pixels of a 256-pixel tile,
                # so this is one tile on each side. A label line then lies
                # whole in each tile it touches at its line_zoom, and each
                # tile finds the same line center.
                "--tile-buffer",
                "256",
            ),
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


# The outline of a region at a pole closes it there. It is not a border.
_POLES = shapely.multilinestrings([[(-180, -90), (180, -90)], [(-180, 90), (180, 90)]])


def write_region_boundaries(regions_parquet: Path, out: Path) -> Path:
    """Write each region border once, as lines with the lowest level it bounds.

    Neighbouring polygons store a shared border once each, in opposite
    directions, and a dash pattern drawn twice looks solid. The outlines of
    each level are snapped to :data:`BOUNDARY_GRID` and noded into one set of
    lines. A second-order border on a first-order border is level 1. The
    outline that closes a region at the antimeridian or at a pole is left
    out. A border at
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
        cuts = shapely.union_all([*(_antimeridian_cut(p) for p in polygons), _POLES])
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


def write_early_lines(lines: Path, out: Path) -> Path:
    """Write the lines that enter before :data:`INTERSECTS_MINZOOM`, with their entry zoom.

    A line enters at the first zoom from :data:`LINES_MINZOOM` at which it
    spans :data:`LINE_MIN_PX` pixels. A main centerline (``is_main``) enters
    at :data:`CENTERLINES_MINZOOM` at the latest. Every other line enters at
    :data:`INTERSECTS_MINZOOM` at the latest.

    Parameters
    ----------
    lines
        The centerlines or the intersects GeoParquet file.
    out
        The GeoParquet file to write, with the entry zoom in ``line_minzoom``.

    Returns
    -------
    Path
        ``out``.
    """
    frame = gpd.read_parquet(lines)
    latest = (
        np.where(frame["is_main"].to_numpy(bool), CENTERLINES_MINZOOM, INTERSECTS_MINZOOM)
        if "is_main" in frame
        else INTERSECTS_MINZOOM
    )
    zooms = span_minzoom(mercator_extent(frame.geometry), LINE_MIN_PX, LINES_MINZOOM, latest)
    early = frame.assign(line_minzoom=zooms.astype("uint8")).loc[zooms < INTERSECTS_MINZOOM]
    out.parent.mkdir(parents=True, exist_ok=True)
    early.to_parquet(out, index=False)
    return out


def version_layers(
    products: dict[str, Path],
    labels: Path,
    region_labels: Path,
    region_boundaries: Path,
    early_lines: dict[str, Path],
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
    early_lines
        The early lines of the centerlines and the intersects, by layer
        name, from :func:`write_early_lines`.
    overviews
        The overview inputs of the glaciers and the complexes, by layer name,
        from :func:`write_overview`.

    Returns
    -------
    list[LayerSpec]
        The regions, their boundaries and their labels at every zoom. The
        complexes and the glaciers as in :func:`glacier_layers`. From
        :data:`LINES_MINZOOM` each early line at its ``line_minzoom``. From
        :data:`INTERSECTS_MINZOOM` all of the centerlines and all of the
        intersects.
    """
    lines = (*LINE_COMPLETE, "--simplify-factor", "0.5")
    divides = (*LINE_COMPLETE, "--simplify-factor", "0")
    # The finest zoom of a tiling keeps every source feature, whatever its
    # entry zoom. The filter keeps a line that enters at CENTERLINES_MINZOOM
    # out of the band before it.
    early_centerlines = (
        *entry_zoom_args("line_minzoom", LINES_MINZOOM, CENTERLINES_MINZOOM - 1),
        "--filter",
        f"line_minzoom < {CENTERLINES_MINZOOM}",
    )
    early_intersects = entry_zoom_args("line_minzoom", LINES_MINZOOM, INTERSECTS_MINZOOM - 1)
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
            early_lines["centerlines"],
            LINES_MINZOOM,
            CENTERLINES_MINZOOM - 1,
            (*lines, *early_centerlines),
            complete=True,
            entry_zoom_column="line_minzoom",
        ),
        # The main centerlines and the long lines. Eleven z8 tiles exceed the
        # size limit.
        LayerSpec(
            "centerlines",
            early_lines["centerlines"],
            CENTERLINES_MINZOOM,
            INTERSECTS_MINZOOM - 1,
            lines,
        ),
        # As the first zoom of a z9-12 band, z9 loses one short centerline.
        # As a band of its own it keeps all of them.
        LayerSpec(
            "centerlines",
            products["centerlines"],
            INTERSECTS_MINZOOM,
            INTERSECTS_MINZOOM,
            lines,
            complete=True,
        ),
        LayerSpec(
            "centerlines",
            products["centerlines"],
            INTERSECTS_MINZOOM + 1,
            MAXZOOM,
            lines,
            complete=True,
        ),
        # Simplification at half a GSD still collapses short divides.
        LayerSpec(
            "intersects",
            early_lines["intersects"],
            LINES_MINZOOM,
            INTERSECTS_MINZOOM - 1,
            (*divides, *early_intersects),
            complete=True,
            entry_zoom_column="line_minzoom",
        ),
        LayerSpec(
            "intersects",
            products["intersects"],
            INTERSECTS_MINZOOM,
            MAXZOOM,
            divides,
            complete=True,
        ),
    ]


def write_web_mercator(source: Path, out: Path, columns: Sequence[str]) -> Path:
    """Write a band's input in Web Mercator, the input the tiler simplifies correctly.

    The tiler simplifies lon/lat input with a tolerance in degrees. On the
    map a degree of latitude is 1/cos(lat) times as long as a degree of
    longitude. At 78°N the outlines moved 2.5 pixels instead of half a pixel.
    Web Mercator input is simplified in map units. The parts beyond
    :data:`MERCATOR_MAX_LAT`, which no tile shows, are cut off.

    Parameters
    ----------
    source
        A GeoParquet file in lon/lat.
    out
        The GeoParquet file to write.
    columns
        The columns to carry.

    Returns
    -------
    Path
        ``out``.
    """
    frame = gpd.read_parquet(source, columns=[*columns, "geometry"])
    geometry = frame.geometry.to_numpy().copy()
    bounds = shapely.bounds(geometry)
    beyond = (bounds[:, 1] < -MERCATOR_MAX_LAT) | (bounds[:, 3] > MERCATOR_MAX_LAT)
    if beyond.any():
        world = shapely.box(-180, -MERCATOR_MAX_LAT, 180, MERCATOR_MAX_LAT)
        geometry[beyond] = shapely.intersection(geometry[beyond], world)
    frame = frame.set_geometry(gpd.GeoSeries(geometry, index=frame.index, crs=frame.crs))
    frame.to_crs(3857).to_parquet(out, index=False)
    return out


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
            source = write_web_mercator(layer.source, work / f"band-{i}.parquet", available)
            _run(
                "tiles",
                source,
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
            source.unlink()
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
    labels = write_labels(products["glaciers"], products["centerlines"], work / "labels.parquet")
    region_labels = write_region_labels(products["regions"], work / "region-labels.parquet")
    region_boundaries = write_region_boundaries(
        products["regions"], work / "region-boundaries.parquet"
    )
    early_lines = {
        name: write_early_lines(products[name], work / f"early-{name}.parquet")
        for name in ("centerlines", "intersects")
    }
    # The overview inputs hold most outlines once per zoom. They go once the
    # archive is built.
    with tempfile.TemporaryDirectory(dir=work, prefix="overview-") as tmp:
        overviews = {
            name: write_overview(products[name], Path(tmp) / name, columns)
            for name, columns in OVERVIEW_COLUMNS.items()
        }
        return build_archive(
            version_layers(
                products, labels, region_labels, region_boundaries, early_lines, overviews
            ),
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
