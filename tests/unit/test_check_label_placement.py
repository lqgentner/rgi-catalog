"""Tests for scripts/check_label_placement.py, on hand-built vector tiles."""

from __future__ import annotations

import gzip
import importlib.util
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from rgi_catalog.paths import REPO

if TYPE_CHECKING:
    from types import ModuleType

KEY = ("RGI2000-v7.0-G-11-00001", 7)


def _load() -> ModuleType:
    path = REPO / "scripts" / "check_label_placement.py"
    spec = importlib.util.spec_from_file_location("check_label_placement", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The script is not a package, so its module has no static type.
placement: Any = _load()


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    return _varint(number << 3 | 2) + _varint(len(value)) + value


def _packed(values: list[int]) -> bytes:
    return b"".join(_varint(v) for v in values)


def _line(points: list[tuple[int, int]]) -> list[int]:
    """Encode a line as MoveTo and LineTo commands."""
    commands = [1 | 1 << 3]
    x = y = 0
    for i, (px, py) in enumerate(points):
        if i == 1:
            commands.append(2 | (len(points) - 1) << 3)
        commands += [_zigzag(px - x), _zigzag(py - y)]
        x, y = px, py
    return commands


def _layer(name: str, features: list[tuple[str, int, list[int]]], extent: int = 4096) -> bytes:
    """Encode a layer of line features with an rgi_id and a label_zoom."""
    keys = [b"rgi_id", b"label_zoom"]
    values: list[bytes] = []
    body = b""
    for rgi_id, label_zoom, commands in features:
        values += [_field(1, rgi_id.encode()), _varint(6 << 3) + _varint(_zigzag(label_zoom))]
        tags = [0, len(values) - 2, 1, len(values) - 1]
        feature = _field(2, _packed(tags)) + _field(3, 2) + _field(4, _packed(commands))
        body += _field(2, feature)
    body += b"".join(_field(3, k) for k in keys) + b"".join(_field(4, v) for v in values)
    return _field(15, 2) + _field(1, name.encode()) + body + _field(5, extent)


def _tile(*layers: bytes) -> bytes:
    return gzip.compress(b"".join(_field(3, layer) for layer in layers))


def test_varint_and_zigzag() -> None:
    assert placement._varint(bytes([0xAC, 0x02]), 0) == (300, 2)
    assert [placement._zigzag(n) for n in (0, 1, 2, 3)] == [0, -1, 1, -2]


def test_parts_split_at_each_move_to() -> None:
    # A MoveTo with a count of 2 starts two parts. ClosePath has no parameters.
    commands = [1 | 2 << 3, _zigzag(10), _zigzag(0), _zigzag(5), _zigzag(5)]
    commands += [2 | 1 << 3, _zigzag(-3), _zigzag(4), 7 | 1 << 3]
    parts = placement._parts(commands)
    assert [p.tolist() for p in parts] == [[[10, 0]], [[15, 5], [12, 9]]]


def test_label_features_read_only_the_label_layer() -> None:
    other = _layer("glaciers", [("other", 7, _line([(0, 0), (9, 9)]))])
    labels = _layer("glacier-labels", [(KEY[0], KEY[1], _line([(100, 50), (300, 50)]))])
    features = placement._label_features(_tile(other, labels))
    assert len(features) == 1
    rgi_id, label_zoom, parts = features[0]
    assert (rgi_id, label_zoom) == KEY
    assert parts[0].tolist() == [[100, 50], [300, 50]]


def test_label_features_refuse_another_extent() -> None:
    labels = _layer("glacier-labels", [(KEY[0], KEY[1], _line([(1, 1), (2, 2)]))], extent=512)
    with pytest.raises(ValueError, match="extent of 512"):
        placement._label_features(_tile(labels))


def test_center_is_the_midpoint_along_the_line() -> None:
    point, length = placement._center(np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]))
    assert point.tolist() == [10.0, 0.0]
    assert length == 20


class _Reader:
    def __init__(self, tiles: dict[tuple[int, int, int], bytes]) -> None:
        self.tiles = tiles

    def get(self, z: int, x: int, y: int) -> bytes | None:
        return self.tiles.get((z, x, y))


def _run(tiles: dict[tuple[int, int, int], bytes]) -> Any:
    placement._reader = _Reader(tiles)
    # Center tile (10, 20). The line is 2,000 tile units long, 250 px at z7.
    placement._lines = {KEY: (10, 20, 2000.0, 100.0, 512 / 4096)}
    return placement._check_tiles(sorted(tiles))


def test_check_tiles_finds_a_whole_line_placed_once() -> None:
    center = _layer("glacier-labels", [(KEY[0], KEY[1], _line([(1000, 2000), (3000, 2000)]))])
    # The neighbour holds the same line in its buffer. Its center lies outside.
    right = _layer("glacier-labels", [(KEY[0], KEY[1], _line([(-3096, 2000), (-1096, 2000)]))])
    whole, placed, unknown = _run({(7, 10, 20): _tile(center), (7, 11, 20): _tile(right)})
    assert whole == [KEY]
    assert placed == [(*KEY, True)]
    assert unknown == set()


def test_check_tiles_counts_a_second_placement_and_a_clipped_line() -> None:
    # The center tile has the line clipped short, and the neighbour places it too.
    center = _layer("glacier-labels", [(KEY[0], KEY[1], _line([(1000, 2000), (2000, 2000)]))])
    right = _layer("glacier-labels", [(KEY[0], KEY[1], _line([(100, 2000), (2100, 2000)]))])
    whole, placed, _ = _run({(7, 10, 20): _tile(center), (7, 11, 20): _tile(right)})
    assert whole == []
    assert [fits for *_, fits in placed] == [True, True]


def test_check_tiles_reports_lines_missing_from_the_label_file() -> None:
    stale = _layer("glacier-labels", [("RGI2000-v7.0-G-11-99999", 7, _line([(1, 1), (9, 9)]))])
    _, _, unknown = _run({(7, 10, 20): _tile(stale)})
    assert unknown == {("RGI2000-v7.0-G-11-99999", 7)}
