"""Check that MapLibre places every glacier label line of the archive once.

Usage::

    pixi run python scripts/check_label_placement.py [ARCHIVE [LABELS]]

ARCHIVE defaults to ``staging/v7.0/rgi7.0.pmtiles``, and LABELS to the label
file that the ``tiles`` step wrote next to it (``.tiles/labels.parquet``).

The check reads the ``glacier-labels`` layer of the tiles, as a client gets
them. For each label line it checks two things:

- The tile that holds the center of the line has the whole line. Each tile
  then finds the same line center.
- MapLibre places the name once. A tile places a ``line-center`` label when
  the center of its part of the line lies in the tile and the label fits
  there (:func:`rgi_catalog.tiles.center_label_fits`, with MapLibre's own
  45° limit). The check counts these placements over the 5 x 5 tiles around
  the center tile.

The script exits with 1 when a line fails a check, and lists the first
problems of each zoom.
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
from typing import Any

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
LAYER_NAME, LAYER_FEATURE, LAYER_KEY, LAYER_VALUE = 1, 2, 3, 4
FEATURE_TAGS, FEATURE_TYPE, FEATURE_GEOMETRY = 2, 3, 4
LINESTRING = 2
VALUE_STRING, VALUE_SINT = 1, 6
MOVE_TO, CLOSE_PATH = 1, 7

# A label line, by (rgi_id, label_zoom): its center tile, its length in tile
# units, its label width in pixels, and pixels per tile unit.
Line = tuple[int, int, float, float, float]

_reader: Reader | None = None
_lines: dict[tuple[str, int], Line] = {}


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


def _init(archive: str, lines: dict[tuple[str, int], Line]) -> None:
    global _reader, _lines  # noqa: PLW0603 - one reader per worker process
    _reader = Reader(MmapSource(Path(archive).open("rb")))  # noqa: SIM115 - lives with the worker
    _lines = lines


def _check_tiles(
    batch: list[tuple[int, int, int]],
) -> tuple[list[tuple[str, int]], list[tuple[str, int, bool]]]:
    """Return the whole lines in their center tiles and the placements, of tiles."""
    if _reader is None:
        msg = "the worker has no archive"
        raise RuntimeError(msg)
    whole: list[tuple[str, int]] = []
    placed: list[tuple[str, int, bool]] = []
    for z, x, y in batch:
        tile = _reader.get(z, x, y)
        if tile is None:
            continue
        for rgi_id, label_zoom, geometry in _label_features(tile):
            line = _lines.get((rgi_id, label_zoom))
            if line is None:
                continue
            tx, ty, length, label_px, px_per_unit = line
            parts = [p for p in geometry if len(p) > 1]
            if (
                (x, y) == (tx, ty)
                and len(parts) == 1
                and abs(_center(parts[0])[1] - length) < LENGTH_TOLERANCE
            ):
                whole.append((rgi_id, label_zoom))
            for part in parts:
                (px, py), _ = _center(part)
                if 0 <= px < EXTENT and 0 <= py < EXTENT:
                    fits = tiles.center_label_fits(
                        part * px_per_unit, label_px, max_angle=MAPLIBRE_MAX_ANGLE
                    )
                    placed.append((rgi_id, label_zoom, fits))
    return whole, placed


def _lines_of(labels: Path) -> dict[tuple[str, int], Line]:
    table = gpd.read_parquet(labels)
    table = table.loc[table["label_zoom"].notna()].to_crs(3857)
    lines: dict[tuple[str, int], Line] = {}
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
        lines[rgi_id, int(label_zoom)] = (
            int(cx // EXTENT),
            int(cy // EXTENT),
            length,
            tiles.label_width_px(name),
            px_per_unit,
        )
    return lines


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
    wanted: set[tuple[int, int, int]] = set()
    for (_, label_zoom), (tx, ty, *_) in lines.items():
        zoom = min(label_zoom, tiles.MAXZOOM)
        n = 2**zoom
        wanted.update(
            (zoom, tx + dx, ty + dy)
            for dx in NEIGHBOURS
            for dy in NEIGHBOURS
            if 0 <= tx + dx < n and 0 <= ty + dy < n
        )
    ordered = sorted(wanted)
    batches = [ordered[i : i + 500] for i in range(0, len(ordered), 500)]
    whole: set[tuple[str, int]] = set()
    placements: collections.Counter[tuple[str, int]] = collections.Counter()
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(str(archive), lines)) as pool:
        for batch_whole, batch_placed in pool.map(_check_tiles, batches):
            whole.update(batch_whole)
            placements.update((rgi_id, z) for rgi_id, z, fits in batch_placed if fits)
    ok = True
    by_zoom: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)
    for key in lines:
        by_zoom[key[1]].append(key)
    for zoom in sorted(by_zoom):
        keys = by_zoom[zoom]
        problems = [k for k in keys if k not in whole or placements[k] != 1]
        print(
            f"z{zoom}: {len(keys)} lines, {sum(k in whole for k in keys)} whole in the center "
            f"tile, {sum(placements[k] == 1 for k in keys)} placed once"
        )
        for rgi_id, _ in problems[:5]:
            print(f"  {rgi_id}: whole={(rgi_id, zoom) in whole} placed={placements[rgi_id, zoom]}")
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
