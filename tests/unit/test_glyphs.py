"""Tests for the glyph advances of the label font."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rgi_catalog import glyphs

if TYPE_CHECKING:
    from pathlib import Path


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _len(field: int, body: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(body)) + body


def _int(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _glyph(code: int, advance: int) -> bytes:
    # A bitmap, width and height sit between the code point and the advance.
    size = _int(3, 1) + _int(4, 1)
    return _len(3, _int(1, code) + _len(2, b"\x00" * 3) + size + _int(7, advance))


PBF = _len(1, _len(1, b"Noto Sans Italic") + _len(2, b"0-255") + _glyph(65, 15) + _glyph(200, 300))


def test_read_advances_reads_code_point_and_advance() -> None:
    assert glyphs.read_advances(PBF) == {65: 15, 200: 300}


def test_write_advances_round_trips(tmp_path: Path) -> None:
    out = glyphs.write_advances(PBF, "https://example.org/0-255.pbf", tmp_path / "a.yaml")
    assert glyphs.load_advances(out) == {65: 15, 200: 300}


def test_recorded_advances_cover_latin_1() -> None:
    advances = glyphs.load_advances()
    assert all(code in advances for code in range(32, 127))
