"""Check that MapLibre places every glacier label line of the archive once.

Usage::

    pixi run python scripts/check_label_placement.py [ARCHIVE [LABELS]]

ARCHIVE defaults to ``staging/v7.0/rgi7.0.pmtiles``, and LABELS to the label
file that the ``tiles`` step wrote next to it (``.tiles/labels.parquet``).

The check reads the ``glacier-labels`` layer of the tiles, as a client gets
them. A glacier can have several label lines at one zoom. The check matches a
line in a tile to the label line with the same center. For each label line it
checks two things:

- The tile that holds the center of the line has the whole line. Each tile
  then finds the same line center.
- MapLibre places the name once. A tile places a ``line-center`` label when
  the center of its part of the line lies in the tile and the label fits
  there. The check counts these placements over the 5 x 5 tiles around the
  center tile.

The fit check is :func:`rgi_catalog.tiles.center_label_fits` with MapLibre's
own 45° limit, and the label width is :func:`rgi_catalog.tiles.label_width_px`.
The ``tiles`` step uses the same port of MapLibre's rule. So the script checks
what the tiler did to the lines: clipping, rounding to the tile grid, the
buffer and the overzoom. It does not check the port itself.

The script exits with 1 when a line fails a check, when a name lands on a
clipped part of a line, when a tile holds a label line that the label file
does not have, or when the label file has no line.
"""

from __future__ import annotations

import argparse
import collections
from concurrent.futures import ProcessPoolExecutor
import gzip
import math
from pathlib import Path
import struct
import sys
from typing import Any, NamedTuple

import geopandas as gpd
import numpy as np
from pmtiles.reader import MmapSource, Reader

from rgi_catalog import tiles
from rgi_catalog.paths import STAGING

LAYER = "glacier-labels"
EXTENT = 4096
WORLD_M = 2 * math.pi * 6378137
# A whole line in the center tile has the length of the source line, up to
# the rounding of its vertices to the tile grid.
LENGTH_TOLERANCE = 8
# MapLibre's text-max-angle, without the reserve that the fit keeps.
MAPLIBRE_MAX_ANGLE = math.radians(45)
NEIGHBOURS = range(-2, 3)

# The protobuf wire types, and the fields of the vector tile messages.
VARINT, FIXED64, LENGTH, FIXED32 = 0, 1, 2, 5
CONTINUATION = 0x80
TILE_LAYER = 3
LAYER_NAME, LAYER_FEATURE, LAYER_KEY, LAYER_VALUE, LAYER_EXTENT = 1, 2, 3, 4, 5
FEATURE_TAGS, FEATURE_TYPE, FEATURE_GEOMETRY = 2, 3, 4
LINESTRING = 2
VALUE_STRING, VALUE_SINT = 1, 6
MOVE_TO, CLOSE_PATH = 1, 7

# A line in a tile belongs to the label line whose center lies within this
# many tile units of its own center.
CENTER_TOLERANCE = 8


class Line(NamedTuple):
    """A label line, in global tile units of the zoom of its tiles."""

    cx: float
    cy: float
    length: float
    # The width of the name, and the pixels per tile unit at label_zoom.
    label_px: float
    px_per_unit: float

    @property
    def tile(self) -> tuple[int, int]:
        """Return the column and row of the tile that holds the center."""
        return int(self.cx // EXTENT), int(self.cy // EXTENT)


# A label line by (rgi_id, label_zoom, index). The index counts the lines of
# a glacier at a zoom in the order of the label file.
Key = tuple[str, int, int]
# The index of a line in a tile that matches no label line.
STRAY = -1

_reader: Reader | None = None
_lines: dict[tuple[str, int], list[Line]] = {}


def _varint(data: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if byte < CONTINUATION:
            return value, i
        shift += 7


def _fields(data: bytes) -> list[tuple[int, Any]]:
    """Return the (field, value) pairs of a protobuf message."""
    out: list[tuple[int, Any]] = []
    i = 0
    while i < len(data):
        key, i = _varint(data, i)
        field, wire = key >> 3, key & 7
        if wire == VARINT:
            value, i = _varint(data, i)
        elif wire == LENGTH:
            length, i = _varint(data, i)
            value = data[i : i + length]
            i += length
        elif wire == FIXED64:
            value = struct.unpack_from("<d", data, i)[0]
            i += 8
        elif wire == FIXED32:
            value = struct.unpack_from("<f", data, i)[0]
            i += 4
        else:
            msg = f"unknown protobuf wire type {wire}"
            raise ValueError(msg)
        out.append((field, value))
    return out


def _packed(data: bytes) -> list[int]:
    out, i = [], 0
    while i < len(data):
        value, i = _varint(data, i)
        out.append(value)
    return out


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _value(data: bytes) -> Any:
    field, value = _fields(data)[0]
    if field == VALUE_STRING:
        return value.decode()
    if field == VALUE_SINT:
        return _zigzag(value)
    return value


def _parts(commands: list[int]) -> list[np.ndarray]:
    """Decode the parts of a line geometry, in tile units."""
    parts: list[list[tuple[int, int]]] = []
    x = y = i = 0
    while i < len(commands):
        command, count = commands[i] & 7, commands[i] >> 3
        i += 1
        if command == CLOSE_PATH:
            continue
        for _ in range(count):
            x += _zigzag(commands[i])
            y += _zigzag(commands[i + 1])
            i += 2
            if command == MOVE_TO:
                parts.append([(x, y)])
            else:
                parts[-1].append((x, y))
    return [np.asarray(p, dtype=float) for p in parts]


def _label_features(tile: bytes) -> list[tuple[str, int, list[np.ndarray]]]:
    """Return the rgi_id, label_zoom and parts of each line in the label layer."""
    raw = gzip.decompress(tile) if tile[:2] == b"\x1f\x8b" else tile
    for field, layer in _fields(raw):
        if field != TILE_LAYER:
            continue
        items = _fields(layer)
        if next(v for f, v in items if f == LAYER_NAME).decode() != LAYER:
            continue
        extent = next((v for f, v in items if f == LAYER_EXTENT), EXTENT)
        if extent != EXTENT:
            msg = f"the {LAYER} layer has an extent of {extent}, not {EXTENT}"
            raise ValueError(msg)
        keys = [v.decode() for f, v in items if f == LAYER_KEY]
        values = [_value(v) for f, v in items if f == LAYER_VALUE]
        out = []
        for feature in (v for f, v in items if f == LAYER_FEATURE):
            fields = dict(_fields(feature))
            if fields.get(FEATURE_TYPE) != LINESTRING:
                continue
            tags = _packed(fields.get(FEATURE_TAGS, b""))
            props = {keys[tags[j]]: values[tags[j + 1]] for j in range(0, len(tags), 2)}
            geometry = _parts(_packed(fields.get(FEATURE_GEOMETRY, b"")))
            out.append((props["rgi_id"], int(props["label_zoom"]), geometry))
        return out
    return []


def _center(coords: np.ndarray) -> tuple[np.ndarray, float]:
    """Return the midpoint of a line and its length."""
    distance = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))])
    half = distance[-1] / 2
    i = min(int(np.searchsorted(distance, half, side="right")) - 1, len(coords) - 2)
    step = distance[i + 1] - distance[i]
    ratio = (half - distance[i]) / step if step > 0 else 0.0
    return coords[i] + ratio * (coords[i + 1] - coords[i]), float(distance[-1])


def _init(archive: str, lines: dict[tuple[str, int], list[Line]]) -> None:
    global _reader, _lines  # noqa: PLW0603 - one reader per worker process
    _reader = Reader(MmapSource(Path(archive).open("rb")))  # noqa: SIM115 - lives with the worker
    _lines = lines


Checked = tuple[list[Key], list[tuple[Key, bool]], set[tuple[str, int]]]


def _match(lines: list[Line], center: np.ndarray) -> int | None:
    """Return the index of the label line with this center, in global tile units."""
    for index, line in enumerate(lines):
        if math.hypot(center[0] - line.cx, center[1] - line.cy) < CENTER_TOLERANCE:
            return index
    return None


def _check_tiles(batch: list[tuple[int, int, int]]) -> Checked:
    """Check the label lines of tiles.

    Returns
    -------
    Checked
        The lines that are whole in their center tile, each placement with
        whether the label fits, and the lines that the label file lacks.
    """
    if _reader is None:
        msg = "the worker has no archive"
        raise RuntimeError(msg)
    whole: list[Key] = []
    placed: list[tuple[Key, bool]] = []
    unknown: set[tuple[str, int]] = set()
    for z, x, y in batch:
        tile = _reader.get(z, x, y)
        if tile is None:
            continue
        for rgi_id, label_zoom, geometry in _label_features(tile):
            lines = _lines.get((rgi_id, label_zoom))
            if lines is None:
                unknown.add((rgi_id, label_zoom))
                continue
            parts = [p for p in geometry if len(p) > 1]
            for part in parts:
                (px, py), part_length = _center(part)
                index = _match(lines, np.array([x * EXTENT + px, y * EXTENT + py]))
                # A tile clips a line that runs past its buffer. The clipped
                # part has a center of its own, and a name there is STRAY.
                key = (rgi_id, label_zoom, STRAY if index is None else index)
                if index is not None:
                    line = lines[index]
                    if (
                        (x, y) == line.tile
                        and len(parts) == 1
                        and abs(part_length - line.length) < LENGTH_TOLERANCE
                    ):
                        whole.append(key)
                if 0 <= px < EXTENT and 0 <= py < EXTENT:
                    # The lines of a glacier at one zoom share the width and scale.
                    fits = tiles.center_label_fits(
                        part * lines[0].px_per_unit,
                        lines[0].label_px,
                        max_angle=MAPLIBRE_MAX_ANGLE,
                    )
                    placed.append((key, fits))
    return whole, placed, unknown


def _lines_of(labels: Path) -> dict[tuple[str, int], list[Line]]:
    table = gpd.read_parquet(labels)
    table = table.loc[table["label_zoom"].notna()].to_crs(3857)
    lines: dict[tuple[str, int], list[Line]] = collections.defaultdict(list)
    for rgi_id, label_zoom, name, geometry in zip(
        table["rgi_id"], table["label_zoom"], table["display_name"], table.geometry, strict=True
    ):
        zoom = min(int(label_zoom), tiles.MAXZOOM)
        unit = WORLD_M / (2**zoom * EXTENT)
        coords = np.asarray(geometry.coords)
        grid = np.column_stack(
            [(coords[:, 0] + WORLD_M / 2) / unit, (WORLD_M / 2 - coords[:, 1]) / unit]
        )
        (cx, cy), length = _center(grid)
        px_per_unit = 2 ** (int(label_zoom) - zoom) * tiles.TILE_PX / EXTENT
        lines[rgi_id, int(label_zoom)].append(
            Line(cx, cy, length, tiles.label_width_px(name), px_per_unit)
        )
    return dict(lines)


def check(archive: Path, labels: Path, workers: int | None = None) -> bool:
    """Check every label line of an archive and print the counts by zoom.

    Parameters
    ----------
    archive
        The PMTiles archive.
    labels
        The label file that the ``tiles`` step wrote for it.
    workers
        The processes. None uses every core.

    Returns
    -------
    bool
        True if every line passes both checks.
    """
    lines = _lines_of(labels)
    if not lines:
        print(f"{labels} has no label line")
        return False
    wanted: set[tuple[int, int, int]] = set()
    for (_, label_zoom), stretches in lines.items():
        zoom = min(label_zoom, tiles.MAXZOOM)
        n = 2**zoom
        # Tile columns wrap at the antimeridian, rows end at the poles.
        wanted.update(
            (zoom, (tx + dx) % n, ty + dy)
            for tx, ty in (line.tile for line in stretches)
            for dx in NEIGHBOURS
            for dy in NEIGHBOURS
            if 0 <= ty + dy < n
        )
    ordered = sorted(wanted)
    batches = [ordered[i : i + 500] for i in range(0, len(ordered), 500)]
    whole: set[Key] = set()
    placements: collections.Counter[Key] = collections.Counter()
    unknown: set[tuple[str, int]] = set()
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(str(archive), lines)) as pool:
        for batch_whole, batch_placed, batch_unknown in pool.map(_check_tiles, batches):
            whole.update(batch_whole)
            placements.update(key for key, fits in batch_placed if fits)
            unknown.update(batch_unknown)
    return _verdict(lines, whole, placements, unknown, labels)


def _verdict(
    lines: dict[tuple[str, int], list[Line]],
    whole: set[Key],
    placements: collections.Counter[Key],
    unknown: set[tuple[str, int]],
    labels: Path,
) -> bool:
    """Print the counts by zoom and the first problems, and return whether all lines pass."""
    stray = sorted(k for k in placements if k[2] == STRAY)
    ok = not unknown and not stray
    if unknown:
        first = sorted(unknown)[:5]
        print(f"{len(unknown)} label lines in the tiles are not in {labels}: {first}")
    if stray:
        msg = f"{len(stray)} glacier zooms have a name on a line that is not a label line"
        print(f"{msg}: {stray[:5]}")
    by_zoom: dict[int, list[Key]] = collections.defaultdict(list)
    for (rgi_id, label_zoom), stretches in lines.items():
        by_zoom[label_zoom].extend((rgi_id, label_zoom, i) for i in range(len(stretches)))
    for zoom in sorted(by_zoom):
        keys = by_zoom[zoom]
        problems = [k for k in keys if k not in whole or placements[k] != 1]
        print(
            f"z{zoom}: {len(keys)} lines, {sum(k in whole for k in keys)} whole in the center "
            f"tile, {sum(placements[k] == 1 for k in keys)} placed once"
        )
        for key in problems[:5]:
            print(f"  {key}: whole={key in whole} placed={placements[key]}")
        ok = ok and not problems
    return ok


def main() -> None:
    """Run the check from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "archive", nargs="?", type=Path, default=STAGING / "v7.0" / "rgi7.0.pmtiles"
    )
    parser.add_argument("labels", nargs="?", type=Path)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    labels = args.labels or args.archive.parent / ".tiles" / "labels.parquet"
    sys.exit(0 if check(args.archive, labels, args.workers) else 1)


if __name__ == "__main__":
    main()
